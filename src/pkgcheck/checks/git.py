"""Various git-related checks."""

import contextlib
import os
import re
import subprocess
import tarfile
from collections import defaultdict
from datetime import datetime
from itertools import chain
from operator import attrgetter
from tempfile import TemporaryDirectory
from urllib.parse import urlparse

from pkgcore.ebuild.misc import sort_keywords
from pkgcore.ebuild.repository import UnconfiguredTree
from pkgcore.fetch import fetchable
from snakeoil import klass
from snakeoil.mappings import ImmutableDict
from snakeoil.osutils import pjoin
from snakeoil.sequences import iflatten_instance
from snakeoil.strings import pluralism

from .. import base, results, sources
from ..addons import git
from ..base import PkgcheckUserException
from . import GentooRepoCheck, GitCommitsCheck
from .header import copyright_regex


class GitCommitsRepoSource(sources.RepoSource):
    """Repository source for locally changed packages in git history.

    Parses git log history to determine packages with changes that
    haven't been pushed upstream yet.
    """

    required_addons = (git.GitAddon,)

    def __init__(self, options, git_addon: git.GitAddon):
        source = git_addon.commits_repo(git.GitChangedRepo)
        super().__init__(options, source)


class GitCommitsSource(sources.Source):
    """Source for local commits in git history.

    Parses git log history to determine commits that haven't been pushed
    upstream yet.
    """

    scope = base.commit_scope
    required_addons = (git.GitAddon,)

    def __init__(self, *args, git_addon: git.GitAddon):
        super().__init__(*args, source=git_addon.commits())


class IncorrectCopyright(results.AliasResult, results.Warning):
    """Changed file with incorrect copyright date."""

    _name = "IncorrectCopyright"

    def __init__(self, year, line, **kwargs):
        super().__init__(**kwargs)
        self.year = year
        self.line = line

    @property
    def desc(self):
        return f"incorrect copyright year {self.year}: {self.line!r}"


class EbuildIncorrectCopyright(IncorrectCopyright, results.VersionResult):
    """Changed ebuild with incorrect copyright date."""


class DirectStableKeywords(results.VersionResult, results.Error):
    """Newly committed ebuild with stable keywords."""

    def __init__(self, keywords, **kwargs):
        super().__init__(**kwargs)
        self.keywords = tuple(keywords)

    @property
    def desc(self):
        s = pluralism(self.keywords)
        keywords = ", ".join(self.keywords)
        return f"directly committed with stable keyword{s}: [ {keywords} ]"


class _DroppedKeywords(results.PackageResult):
    """Unstable keywords dropped from package."""

    _status = None

    def __init__(self, keywords, commit, **kwargs):
        super().__init__(**kwargs)
        self.keywords = tuple(keywords)
        self.commit = str(commit)

    @property
    def desc(self):
        s = pluralism(self.keywords)
        keywords = ", ".join(self.keywords)
        return f"commit {self.commit} (or later) dropped {self._status} keyword{s}: [ {keywords} ]"


class DroppedUnstableKeywords(_DroppedKeywords, results.Error):
    """Unstable keywords dropped from package."""

    _status = "unstable"


class DroppedStableKeywords(_DroppedKeywords, results.Error):
    """Stable keywords dropped from package."""

    _status = "stable"


class DirectNoMaintainer(results.PackageResult, results.Error):
    """Directly added, new package with no specified maintainer."""

    @property
    def desc(self):
        return "directly committed with no package maintainer"


class RdependChange(results.VersionResult, results.Warning):
    """Package RDEPEND was modified without adding a new ebuild revision."""

    @property
    def desc(self):
        return "RDEPEND modified without revbump"


class MissingSlotmove(results.VersionResult, results.Error):
    """Package SLOT was changed without adding a slotmove package update.

    When changing an existing ebuild's SLOT, a new entry must be
    created in profiles/updates. See the devmanual [#]_ for more info.

    .. [#] https://devmanual.gentoo.org/ebuild-maintenance/package-moves/
    """

    def __init__(self, old, new, **kwargs):
        super().__init__(**kwargs)
        self.old = old
        self.new = new

    @property
    def desc(self):
        return f"changed SLOT: {self.old} -> {self.new}"


class MissingMove(results.PackageResult, results.Error):
    """Package was renamed without adding a move package update.

    When moving/renaming a package, a new entry must be created in
    profiles/updates. See the devmanual [#]_ for more info.

    .. [#] https://devmanual.gentoo.org/ebuild-maintenance/package-moves/
    """

    def __init__(self, old, new, **kwargs):
        super().__init__(**kwargs)
        self.old = old
        self.new = new

    @property
    def desc(self):
        return f"renamed package: {self.old} -> {self.new}"


class PythonPEP517WithoutRevbump(results.PackageResult, results.Warning):
    """Package has started/stopped using DISTUTILS_USE_PEP517 without revbump.

    The package has started or stopped using DISTUTILS_USE_PEP517 without
    a new revision. PEP517 affects the files installed by a package
    and might lead to some files missing.

    """

    desc = "changed DISTUTILS_USE_PEP517 without new revision"


class EAPIChangeWithoutRevbump(results.PackageResult, results.Warning):
    """Package has changed EAPI without revbump.

    The package has changed EAPI without a new revision. An EAPI bump
    might affect the installed files (EAPI changes, eclass functions
    may change behavior, new portage features might be used, etc.).
    The change should also be reflected in the vdb's EAPI file.
    """

    desc = "changed EAPI without new revision"


class SrcUriChecksumChange(results.PackageResult, results.Error):
    """SRC_URI changing checksum without distfile rename."""

    def __init__(self, filename, **kwargs):
        super().__init__(**kwargs)
        self.filename = filename

    @property
    def desc(self):
        return f"{self.filename!r} has different checksums across commits"


class SuspiciousSrcUriChange(results.PackageResult, results.Warning):
    """Suspicious SRC_URI changing URI without distfile rename."""

    def __init__(self, old_uri: str, new_uri: str, filename: str, **kwargs):
        super().__init__(**kwargs)
        self.old_uri = old_uri
        self.new_uri = new_uri
        self.filename = filename

    @property
    def desc(self):
        return f"{self.filename!r} has changed SRC_URI from {self.old_uri!r} to {self.new_uri!r}"


class OldPythonCompat(results.VersionResult, results.Warning):
    """Package still lists old targets in ``PYTHON_COMPAT``."""

    def __init__(self, old_targets, **kwargs):
        super().__init__(**kwargs)
        self.old_targets = tuple(old_targets)

    @property
    def desc(self):
        s = pluralism(self.old_targets)
        targets = ", ".join(self.old_targets)
        return f"old PYTHON_COMPAT target{s} listed: [ {targets} ]"


class NewerEAPIAvailable(results.VersionResult, results.Warning):
    """Package is eligible for a newer EAPI.

    A new package version was added, using an older EAPI, than all supported by
    inherited eclasses. You should consider bumping the EAPI to the suggested
    value.
    """

    def __init__(self, eapi: int, **kwargs):
        super().__init__(**kwargs)
        self.eapi = eapi

    @property
    def desc(self):
        return f"ebuild eligible for newer EAPI={self.eapi}"


class _RemovalRepo(UnconfiguredTree):
    """Repository of removed packages stored in a temporary directory."""

    def __init__(self, repo):
        self.__parent_repo = repo
        self.__tmpdir = TemporaryDirectory(prefix="tmp-pkgcheck-", suffix=".repo")
        self.__created = False
        repo_dir = self.__tmpdir.name

        # set up some basic repo files so pkgcore doesn't complain
        os.makedirs(pjoin(repo_dir, "metadata"))
        with open(pjoin(repo_dir, "metadata", "layout.conf"), "w") as f:
            f.write(f"masters = {' '.join(x.repo_id for x in repo.trees)}\n")
        os.makedirs(pjoin(repo_dir, "profiles"))
        with open(pjoin(repo_dir, "profiles", "repo_name"), "w") as f:
            f.write("old-repo\n")
        super().__init__(repo_dir)

    def cleanup(self):
        self.__tmpdir.cleanup()

    def __call__(self, pkgs):
        """Update the repo with a given sequence of packages."""
        self._populate(pkgs)
        if self.__created:
            # notify the repo object that new pkgs were added
            for pkg in pkgs:
                self.notify_add_package(pkg)
        self.__created = True
        return self

    def _populate(self, pkgs):
        """Populate the repo with a given sequence of historical packages."""
        pkg = min(pkgs, key=attrgetter("time"))
        paths = [pjoin(pkg.category, pkg.package)]
        for subdir in ("eclass", "profiles"):
            if os.path.exists(pjoin(self.__parent_repo.location, subdir)):
                paths.append(subdir)
        old_files = subprocess.Popen(
            ["git", "archive", f"{pkg.commit}~1"] + paths,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self.__parent_repo.location,
        )
        if old_files.poll():
            error = old_files.stderr.read().decode().strip()
            raise PkgcheckUserException(f"failed populating archive repo: {error}")
        # https://docs.python.org/3.12/library/tarfile.html#tarfile-extraction-filter
        if hasattr(tarfile, "data_filter"):
            # https://docs.python.org/3.12/library/tarfile.html#tarfile.TarFile.extraction_filter
            tarfile.TarFile.extraction_filter = staticmethod(tarfile.data_filter)
        with tarfile.open(mode="r|", fileobj=old_files.stdout) as tar:
            tar.extractall(path=self.location)


class GitPkgCommitsCheck(GentooRepoCheck, GitCommitsCheck):
    """Check unpushed git package commits for various issues."""

    _source = (sources.PackageRepoSource, (), (("source", GitCommitsRepoSource),))
    required_addons = (git.GitAddon, sources.EclassAddon)
    known_results = frozenset(
        {
            DirectStableKeywords,
            DirectNoMaintainer,
            RdependChange,
            EbuildIncorrectCopyright,
            DroppedStableKeywords,
            DroppedUnstableKeywords,
            MissingSlotmove,
            MissingMove,
            SrcUriChecksumChange,
            SuspiciousSrcUriChange,
            PythonPEP517WithoutRevbump,
            EAPIChangeWithoutRevbump,
            OldPythonCompat,
            NewerEAPIAvailable,
        }
    )

    python_pep517_regex = re.compile("^DISTUTILS_USE_PEP517=")
    python_compat_declare_regex = re.compile(r"^declare -a PYTHON_COMPAT=(?P<value>.+)$")
    env_array_elem_regex = re.compile(r'\[\d+\]="(?P<val>.+?)"')

    # package categories that are committed with stable keywords
    allowed_direct_stable = frozenset(["acct-user", "acct-group", "sec-keys", "virtual"])

    def __init__(self, *args, git_addon: git.GitAddon, eclass_addon: sources.EclassAddon):
        super().__init__(*args)
        self.today = datetime.today()
        self.repo = self.options.target_repo
        self.valid_arches: frozenset[str] = self.options.target_repo.known_arches
        self._git_addon = git_addon
        self.eclass_cache = eclass_addon.eclasses
        self._cleanup = []
        self.valid_python_targets = {
            use.removeprefix("python_targets_")
            for use, _ in self.repo.use_expand_desc.get("python_targets", ())
        }

    def cleanup(self):
        for repo in self._cleanup:
            repo.cleanup()

    @klass.jit_attr
    def removal_repo(self):
        """Create a repository of packages removed from git."""
        self._cleanup.append(repo := _RemovalRepo(self.repo))
        return repo

    @klass.jit_attr
    def modified_repo(self):
        """Create a repository of old packages newly modified in git."""
        self._cleanup.append(repo := _RemovalRepo(self.repo))
        return repo

    @klass.jit_attr
    def added_repo(self):
        """Create/load cached repo of packages added to git."""
        return self._git_addon.cached_repo(git.GitAddedRepo)

    def addition_checks(self, pkgs):
        """Check for issues due to package additions."""
        pkg = pkgs[0]
        try:
            new_pkg = self.repo.match(pkg.versioned_atom)[0]
        except IndexError:
            # ignore missing ebuild
            return

        if new_pkg.inherit:
            eclass_eapis = (
                frozenset(map(int, self.eclass_cache[eclass].supported_eapis))
                for eclass in new_pkg.inherit
            )
            current_eapi = int(str(new_pkg.eapi))
            common_max_eapi = max(frozenset.intersection(*eclass_eapis), default=0)
            if common_max_eapi > current_eapi:
                yield NewerEAPIAvailable(common_max_eapi, pkg=new_pkg)

    def removal_checks(self, pkgs):
        """Check for issues due to package removals."""
        pkg = pkgs[0]
        removal_repo = self.removal_repo(pkgs)

        old_keywords = set().union(*(p.keywords for p in removal_repo.match(pkg.unversioned_atom)))
        new_keywords = set().union(*(p.keywords for p in self.repo.match(pkg.unversioned_atom)))

        dropped_keywords: set[str] = old_keywords - new_keywords
        dropped_stable_keywords = dropped_keywords & self.valid_arches
        dropped_unstable_keywords = set()
        for keyword in (x for x in dropped_keywords if x[0] == "~"):
            arch = keyword[1:]
            if arch in self.valid_arches and arch not in new_keywords:
                dropped_unstable_keywords.add(keyword)

        if dropped_stable_keywords:
            yield DroppedStableKeywords(sort_keywords(dropped_stable_keywords), pkg.commit, pkg=pkg)
        if dropped_unstable_keywords:
            yield DroppedUnstableKeywords(
                sort_keywords(dropped_unstable_keywords), pkg.commit, pkg=pkg
            )

    def rename_checks(self, pkgs):
        """Check for issues due to package modifications."""
        pkg = pkgs[0]
        old_key, new_key = pkg.old.key, pkg.key

        # same package, probably version bump and remove old
        if old_key == new_key:
            return

        pkgmoves = (x[1:] for x in self.repo.config.updates.get(old_key, ()) if x[0] == "move")

        for old, new in pkgmoves:
            if old.key == old_key and new.key == new_key:
                break
        else:
            yield MissingMove(old_key, new_key, pkg=pkg)

    def modified_checks(self, pkgs, added):
        """Check for issues due to package modifications."""
        pkg = pkgs[0]

        try:
            new_pkg = self.repo.match(pkg.versioned_atom)[0]
        except IndexError:
            # ignore broken ebuild
            return

        # ignore live ebuilds
        if new_pkg.live:
            return

        modified_repo = self.modified_repo(pkgs)
        try:
            old_pkg = modified_repo.match(pkg.versioned_atom)[0]
        except IndexError:
            # ignore broken ebuild
            return

        if pkg not in added and old_pkg.rdepend != new_pkg.rdepend:
            yield RdependChange(pkg=new_pkg)

        if "distutils-r1" in new_pkg.inherited:

            def found_pep517_lines(cmp_pkg):
                return any(
                    self.python_pep517_regex.match(line) for line in cmp_pkg.ebuild.text_fileobj()
                )

            found_old_pep517_line = found_pep517_lines(old_pkg)
            found_new_pep517_line = found_pep517_lines(new_pkg)

            if found_old_pep517_line ^ found_new_pep517_line:
                yield PythonPEP517WithoutRevbump(pkg=new_pkg)

        if old_pkg.eapi != new_pkg.eapi:
            yield EAPIChangeWithoutRevbump(pkg=new_pkg)

        old_slot, new_slot = old_pkg.slot, new_pkg.slot
        if old_slot != new_slot:
            slotmoves = (
                x[1:] for x in self.repo.config.updates.get(new_pkg.key, ()) if x[0] == "slotmove"
            )
            for atom, moved_slot in slotmoves:
                if atom.match(old_pkg) and new_slot == moved_slot:
                    break
            else:
                yield MissingSlotmove(old_slot, new_slot, pkg=new_pkg)

        with contextlib.suppress(Exception):
            for env_line in new_pkg.environment.data.splitlines():
                if mo := self.python_compat_declare_regex.match(env_line):
                    if old_compat := {
                        m.group("val")
                        for m in re.finditer(self.env_array_elem_regex, mo.group("value"))
                    }.difference(self.valid_python_targets):
                        yield OldPythonCompat(sorted(old_compat), pkg=new_pkg)

    def _fetchable_str(self, fetch: fetchable) -> tuple[str, str]:
        uri = tuple(fetch.uri._uri_source)[0]
        if isinstance(uri, tuple):
            mirror = uri[0].mirror_name
            expands = self.repo.mirrors.get(mirror)
            expand = (expands or (f"mirror://{mirror}",))[0].lstrip("/")
            return f"{expand}/{uri[1]}", f"mirror://{uri[0].mirror_name}/{uri[1]}"
        else:
            return (str(uri),) * 2

    def src_uri_changes(self, pkgset):
        pkg = pkgset[0].unversioned_atom

        try:
            new_checksums = {
                fetch.filename: (fetch.chksums, self._fetchable_str(fetch))
                for pkg in self.repo.match(pkg)
                for fetch in iflatten_instance(
                    pkg.generate_fetchables(
                        allow_missing_checksums=True,
                        ignore_unknown_mirrors=True,
                        skip_default_mirrors=True,
                    ),
                    fetchable,
                )
                if fetch.chksums
            }

            old_checksums = {
                fetch.filename: (fetch.chksums, self._fetchable_str(fetch))
                for pkg in self.modified_repo(pkgset).match(pkg)
                for fetch in iflatten_instance(
                    pkg.generate_fetchables(
                        allow_missing_checksums=True,
                        ignore_unknown_mirrors=True,
                        skip_default_mirrors=True,
                    ),
                    fetchable,
                )
                if fetch.chksums
            }
        except (IndexError, FileNotFoundError, tarfile.ReadError):
            # ignore broken ebuild
            return

        for filename in old_checksums.keys() & new_checksums.keys():
            old_checksum, (old_expand, old_uri) = old_checksums[filename]
            new_checksum, (new_expand, new_uri) = new_checksums[filename]
            if old_checksum != new_checksum:
                yield SrcUriChecksumChange(filename, pkg=pkg)
            elif old_expand != new_expand:
                yield SuspiciousSrcUriChange(old_uri, new_uri, filename, pkg=pkg)

    def feed(self, pkgset: list[git.GitPkgChange]):
        # Mapping of commit types to pkgs, available commit types can be seen
        # under the --diff-filter option in git log parsing support and are
        # disambiguated as follows:
        # A -> added, R -> renamed, M -> modified, D -> deleted
        pkg_map = {"A": set(), "R": set(), "M": set(), "D": set()}
        # Iterate over pkg commits in chronological order (git log defaults to
        # the reverse) discarding matching pkg commits where relevant.
        for pkg in reversed(pkgset):
            pkg_map[pkg.status].add(pkg)
            if pkg.status == "A":
                pkg_map["D"].discard(pkg)
            elif pkg.status == "D":
                pkg_map["A"].discard(pkg)
            elif pkg.status == "R":
                # create pkg add/removal for rename operation
                pkg_map["A"].add(pkg)
                pkg_map["D"].add(pkg.old_pkg())

        # run added package checks
        if pkg_map["A"]:
            yield from self.addition_checks(list(pkg_map["A"]))
        # run removed package checks
        if pkg_map["D"]:
            yield from self.removal_checks(list(pkg_map["D"]))
        # run renamed package checks
        if pkg_map["R"]:
            yield from self.rename_checks(list(pkg_map["R"]))
        # run modified package checks
        if modified := [pkg for pkg in pkg_map["M"] if pkg not in pkg_map["D"]]:
            version_modifications = defaultdict(list)
            for pkg in modified:
                version_modifications[pkg.fullver].append(pkg)
            for modified in version_modifications.values():
                yield from self.modified_checks(modified, pkg_map["A"])

        for git_pkg in pkgset:
            # remaining checks are irrelevant for removed packages
            if git_pkg in pkg_map["D"]:
                continue

            # pull actual package object from repo
            try:
                pkg = next(self.repo.itermatch(git_pkg.versioned_atom))
                line = next(pkg.ebuild.text_fileobj())
            except StopIteration:
                # ignore broken ebuild caught by other checks
                continue

            # check copyright on new/modified ebuilds
            if mo := copyright_regex.match(line):
                year = mo.group("end")
                if int(year) != self.today.year:
                    yield EbuildIncorrectCopyright(year, line.strip("\n"), pkg=pkg)

            # checks for newly added ebuilds
            if git_pkg.status == "A":
                # check for directly added stable ebuilds
                if pkg.category not in self.allowed_direct_stable:
                    if stable_keywords := sorted(x for x in pkg.keywords if x[0] not in "~-"):
                        yield DirectStableKeywords(stable_keywords, pkg=pkg)

                # pkg was just added to the tree
                newly_added = not self.added_repo.match(git_pkg.unversioned_atom)

                # check for no maintainers
                if not pkg.maintainers and newly_added:
                    yield DirectNoMaintainer(pkg=pkg)

        yield from self.src_uri_changes(pkgset)


class MissingSignOff(results.CommitResult, results.Error):
    """Local commit with missing sign offs.

    Sign offs are required for commits as specified by GLEP 76 [#]_. Note that
    sign off tags will be flagged if the name or email address doesn't match
    the values used by the commit author.

    .. [#] https://www.gentoo.org/glep/glep-0076.html#certificate-of-origin
    """

    def __init__(self, missing_sign_offs, **kwargs):
        super().__init__(**kwargs)
        self.missing_sign_offs = tuple(missing_sign_offs)

    @property
    def desc(self):
        s = pluralism(self.missing_sign_offs)
        sign_offs = ", ".join(self.missing_sign_offs)
        return f"commit {self.commit}, missing sign-off{s}: {sign_offs}"


class InvalidCommitTag(results.CommitResult, results.Style):
    """Local commit has a tag that is incompliant.

    Commit tags have restrictions as to the allowed format and data
    used per GLEP 66 [#]_.

    .. [#] https://www.gentoo.org/glep/glep-0066.html#commit-messages
    """

    def __init__(self, tag: str, value: str, error: str, **kwargs):
        super().__init__(**kwargs)
        self.tag, self.value, self.error = tag, value, error

    @property
    def desc(self):
        return f'commit {self.commit}, tag "{self.tag}: {self.value}": {self.error}'


class InvalidCommitMessage(results.CommitResult, results.Style):
    """Local commit has issues with its commit message."""

    def __init__(self, error, **kwargs):
        super().__init__(**kwargs)
        self.error = error

    @property
    def desc(self):
        return f"commit {self.commit}: {self.error}"


class BadCommitSummary(results.CommitResult, results.Style):
    """Local package commit with poorly formatted or unmatching commit summary.

    Git commit messages for packages should be formatted in the standardized
    fashion described in the devmanual [#]_. Specifically, a
    ``${CATEGORY}/${PN}:`` or ``${CATEGORY}/${P}:`` prefix should be used in
    the summary relating to the modified package.

    .. [#] https://devmanual.gentoo.org/ebuild-maintenance/git/#git-commit-message-format
    """

    def __init__(self, error, summary, **kwargs):
        super().__init__(**kwargs)
        self.error = error
        self.summary = summary

    @property
    def desc(self):
        return f"commit {self.commit}, {self.error}: {self.summary!r}"


def verify_tags(*tags: str, required: bool = False):
    """Decorator to register commit tag verification methods."""

    class decorator:
        """Decorator with access to the class of a decorated function."""

        def __init__(self, func):
            self.func = func

        def __set_name__(self, owner, name):
            for tag in tags:
                owner.known_tags[tag] = (self.func, required)
            setattr(owner, name, self.func)

    return decorator


class GitCommitMessageCheck(GentooRepoCheck, GitCommitsCheck):
    """Check unpushed git commit messages for various issues."""

    _source = GitCommitsSource
    known_results = frozenset(
        {
            MissingSignOff,
            InvalidCommitTag,
            InvalidCommitMessage,
            BadCommitSummary,
        }
    )

    # mapping between known commit tags and verification methods
    known_tags = {}
    _commit_footer_regex = re.compile(r"^(?P<tag>[a-zA-Z0-9_-]+): (?P<value>.*)$")
    _git_cat_file_regex = re.compile(r"^(?P<object>.+?) (?P<status>.+)$")
    _commit_ref_regex = re.compile(r"^(?P<object>[0-9a-fA-F]+?)( \(.+?\))?\.?$")

    # categories exception for rule of having package version in summary
    skipped_categories = frozenset(
        {
            "acct-group",
            "acct-user",
            "virtual",
        }
    )

    def __init__(self, *args):
        super().__init__(*args)
        # mapping of required tags to forcibly run verifications methods
        self._required_tags = ImmutableDict(
            ((tag, verify), []) for tag, (verify, required) in self.known_tags.items() if required
        )

    @verify_tags("Signed-off-by", required=True)
    def _signed_off_by_tag(self, tag: str, values: list[str], commit: git.GitCommit):
        """Verify commit contains all required sign offs in accordance with GLEP 76."""
        required_sign_offs = {commit.author, commit.committer}
        if missing_sign_offs := required_sign_offs.difference(values):
            yield MissingSignOff(sorted(missing_sign_offs), commit=commit)

    @verify_tags("Gentoo-Bug")
    def _deprecated_tag(self, tag: str, values: list[str], commit: git.GitCommit):
        """Flag deprecated tags that shouldn't be used."""
        for value in values:
            yield InvalidCommitTag(tag, value, f"{tag} tag is no longer valid", commit=commit)

    @verify_tags("Bug", "Closes")
    def _bug_tag(self, tag: str, values: list[str], commit: git.GitCommit):
        """Verify values are URLs for Bug/Closes tags."""
        for value in values:
            parsed = urlparse(value)
            if not parsed.scheme:
                yield InvalidCommitTag(tag, value, "value isn't a URL", commit=commit)
                continue
            if parsed.scheme.lower() not in ("http", "https"):
                yield InvalidCommitTag(
                    tag, value, "invalid protocol; should be http or https", commit=commit
                )

    @klass.jit_attr_none
    def git_cat_file(self):
        """Start a `git cat-file` process to verify git repo hashes."""
        return subprocess.Popen(
            ["git", "cat-file", "--batch-check"],
            cwd=self.options.target_repo.location,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            encoding="utf8",
            bufsize=1,
        )

    @verify_tags("Fixes", "Reverts")
    def _commit_tag(self, tag, values, commit: git.GitCommit):
        """Verify referenced commits exist for Fixes/Reverts tags."""
        commits: dict[str, str] = {}
        for value in values:
            if mo := self._commit_ref_regex.match(value):
                commits[mo.group("object")] = value
            else:
                yield InvalidCommitTag(tag, value, "invalid format", commit=commit)
        self.git_cat_file.stdin.write("\n".join(commits.keys()) + "\n")
        if self.git_cat_file.poll() is None:
            for _ in range(len(commits)):
                line = self.git_cat_file.stdout.readline().strip()
                if mo := self._git_cat_file_regex.match(line):
                    value = mo.group("object")
                    status = mo.group("status")
                    if not status.startswith("commit "):
                        yield InvalidCommitTag(
                            tag, commits[value], f"{status} commit", commit=commit
                        )

    def feed(self, commit: git.GitCommit):
        if len(commit.message) == 0:
            yield InvalidCommitMessage("no commit message", commit=commit)
            return

        # drop leading '*: ' prefix assuming it's a package/eclass/file/path
        summary = commit.message[0]
        if len(summary.split(": ", 1)[-1]) > 69:
            yield InvalidCommitMessage("summary is too long", commit=commit)

        # categorize package changes
        pkg_changes = defaultdict(set)
        for atom in chain.from_iterable(commit.pkgs.values()):
            pkg_changes[atom.category].add(atom)

        # check git commit summary formatting
        if len(pkg_changes) == 1:
            category, atoms = pkg_changes.popitem()
            if len({x.package for x in atoms}) == 1:
                # changes to a single cat/pn
                atom = next(iter(atoms))
                if not re.match(rf"^{re.escape(atom.key)}: ", summary):
                    error = f"summary missing {atom.key!r} package prefix"
                    yield BadCommitSummary(error, summary, commit=commit)
                # check for version in summary for singular, non-revision bumps
                if len(commit.pkgs["A"]) == 1 and category not in self.skipped_categories:
                    atom = next(iter(commit.pkgs["A"]))
                    if not atom.revision and not re.match(
                        rf"^.+\bv?{re.escape(atom.version)}\b.*$", summary
                    ):
                        error = f"summary missing package version {atom.version!r}"
                        yield BadCommitSummary(error, summary, commit=commit)
            else:
                # mutiple pkg changes in the same category
                if not re.match(rf"^{re.escape(category)}: ", summary):
                    error = f"summary missing {category!r} category prefix"
                    yield BadCommitSummary(error, summary, commit=commit)

        # verify message body
        i = iter(commit.message[1:])
        lineno = 1
        body = False
        for lineno, line in enumerate(i, lineno):
            if not line.strip():
                continue
            if self._commit_footer_regex.match(line) is None:
                if not body and commit.message[1] != "":
                    yield InvalidCommitMessage("missing empty line before body", commit=commit)
                # still processing the body
                body = True
                if len(line.split()) > 1 and len(line) > 80:
                    yield InvalidCommitMessage(
                        f"line {lineno} greater than 80 chars: {line!r}", commit=commit
                    )
            else:
                if commit.message[lineno - 1] != "":
                    yield InvalidCommitMessage("missing empty line before tags", commit=commit)
                # push it back on the stack
                i = chain([line], i)
                break

        # mapping of defined tags to any existing verification methods
        tags = dict(self._required_tags)

        # verify footer
        for lineno, line in enumerate(i, lineno + 1):
            if not line.strip():
                # single empty end line is ignored
                if lineno != len(commit.message):
                    yield InvalidCommitMessage(f"empty line {lineno} in footer", commit=commit)
                continue
            if mo := self._commit_footer_regex.match(line):
                # register known tags for verification
                tag = mo.group("tag")
                try:
                    func, required = self.known_tags[tag]
                    tags.setdefault((tag, func), []).append(mo.group("value"))
                except KeyError:
                    continue
            else:
                yield InvalidCommitMessage(
                    f"non-tag in footer, line {lineno}: {line!r}", commit=commit
                )

        # run tag verification methods
        for (tag, func), values in tags.items():
            yield from func(self, tag, values, commit)


class EclassIncorrectCopyright(IncorrectCopyright, results.EclassResult):
    """Changed eclass with incorrect copyright date."""

    @property
    def desc(self):
        return f"{self.eclass}: {super().desc}"


class GitEclassCommitsCheck(GentooRepoCheck, GitCommitsCheck):
    """Check unpushed git eclass commits for various issues."""

    _source = sources.EclassRepoSource
    known_results = frozenset([EclassIncorrectCopyright])

    def __init__(self, *args):
        super().__init__(*args)
        self.today = datetime.today()

    def feed(self, eclass):
        # check copyright on new/modified eclasses
        line = next(iter(eclass.lines))
        if mo := copyright_regex.match(line):
            year = mo.group("end")
            if int(year) != self.today.year:
                yield EclassIncorrectCopyright(year, line.strip("\n"), eclass=eclass)
