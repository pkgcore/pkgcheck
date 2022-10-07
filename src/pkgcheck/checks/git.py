"""Various git-related checks."""

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
from snakeoil import klass
from snakeoil.mappings import ImmutableDict
from snakeoil.osutils import pjoin
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

    def __init__(self, options, git_addon):
        source = git_addon.commits_repo(git.GitChangedRepo)
        super().__init__(options, source)


class GitCommitsSource(sources.Source):
    """Source for local commits in git history.

    Parses git log history to determine commits that haven't been pushed
    upstream yet.
    """

    scope = base.commit_scope
    required_addons = (git.GitAddon,)

    def __init__(self, *args, git_addon):
        super().__init__(*args, source=git_addon.commits())


class IncorrectCopyright(results.AliasResult, results.Warning):
    """Changed file with incorrect copyright date."""

    _name = 'IncorrectCopyright'

    def __init__(self, year, line, **kwargs):
        super().__init__(**kwargs)
        self.year = year
        self.line = line

    @property
    def desc(self):
        return f'incorrect copyright year {self.year}: {self.line!r}'


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
        keywords = ', '.join(self.keywords)
        return f'directly committed with stable keyword{s}: [ {keywords} ]'


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
        keywords = ', '.join(self.keywords)
        return (
            f'commit {self.commit} (or later) dropped {self._status} '
            f'keyword{s}: [ {keywords} ]'
        )


class DroppedUnstableKeywords(_DroppedKeywords, results.Error):
    """Unstable keywords dropped from package."""

    _status = 'unstable'


class DroppedStableKeywords(_DroppedKeywords, results.Error):
    """Stable keywords dropped from package."""

    _status = 'stable'


class DirectNoMaintainer(results.PackageResult, results.Error):
    """Directly added, new package with no specified maintainer."""

    @property
    def desc(self):
        return 'directly committed with no package maintainer'


class RdependChange(results.VersionResult, results.Warning):
    """Package RDEPEND was modified without adding a new ebuild revision."""

    @property
    def desc(self):
        return 'RDEPEND modified without revbump'


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
        return f'changed SLOT: {self.old} -> {self.new}'


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
        return f'renamed package: {self.old} -> {self.new}'


class _RemovalRepo(UnconfiguredTree):
    """Repository of removed packages stored in a temporary directory."""

    def __init__(self, repo):
        self.__parent_repo = repo
        self.__tmpdir = TemporaryDirectory(prefix='tmp-pkgcheck-', suffix='.repo')
        self.__created = False
        repo_dir = self.__tmpdir.name

        # set up some basic repo files so pkgcore doesn't complain
        os.makedirs(pjoin(repo_dir, 'metadata'))
        with open(pjoin(repo_dir, 'metadata', 'layout.conf'), 'w') as f:
            f.write(f"masters = {' '.join(x.repo_id for x in repo.trees)}\n")
        os.makedirs(pjoin(repo_dir, 'profiles'))
        with open(pjoin(repo_dir, 'profiles', 'repo_name'), 'w') as f:
            f.write('old-repo\n')
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
        pkg = min(pkgs, key=attrgetter('time'))
        paths = [pjoin(pkg.category, pkg.package)]
        for subdir in ('eclass', 'profiles'):
            if os.path.exists(pjoin(self.__parent_repo.location, subdir)):
                paths.append(subdir)
        old_files = subprocess.Popen(
            ['git', 'archive', f'{pkg.commit}~1'] + paths,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=self.__parent_repo.location)
        if old_files.poll():
            error = old_files.stderr.read().decode().strip()
            raise PkgcheckUserException(f'failed populating archive repo: {error}')
        with tarfile.open(mode='r|', fileobj=old_files.stdout) as tar:
            tar.extractall(path=self.location)


class GitPkgCommitsCheck(GentooRepoCheck, GitCommitsCheck):
    """Check unpushed git package commits for various issues."""

    _source = (sources.PackageRepoSource, (), (('source', GitCommitsRepoSource),))
    required_addons = (git.GitAddon,)
    known_results = frozenset([
        DirectStableKeywords, DirectNoMaintainer, RdependChange, EbuildIncorrectCopyright,
        DroppedStableKeywords, DroppedUnstableKeywords, MissingSlotmove, MissingMove,
    ])

    # package categories that are committed with stable keywords
    allowed_direct_stable = frozenset(['acct-user', 'acct-group'])

    def __init__(self, *args, git_addon):
        super().__init__(*args)
        self.today = datetime.today()
        self.repo = self.options.target_repo
        self.valid_arches = self.options.target_repo.known_arches
        self._git_addon = git_addon
        self._cleanup = []

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

    def removal_checks(self, pkgs):
        """Check for issues due to package removals."""
        pkg = pkgs[0]
        removal_repo = self.removal_repo(pkgs)

        old_keywords = set().union(*(
            p.keywords for p in removal_repo.match(pkg.unversioned_atom)))
        new_keywords = set().union(*(
            p.keywords for p in self.repo.match(pkg.unversioned_atom)))

        dropped_keywords = old_keywords - new_keywords
        dropped_stable_keywords = dropped_keywords & self.valid_arches
        dropped_unstable_keywords = set()
        for keyword in (x for x in dropped_keywords if x[0] == '~'):
            arch = keyword[1:]
            if arch in self.valid_arches and arch not in new_keywords:
                dropped_unstable_keywords.add(keyword)

        if dropped_stable_keywords:
            yield DroppedStableKeywords(
                sort_keywords(dropped_stable_keywords), pkg.commit, pkg=pkg)
        if dropped_unstable_keywords:
            yield DroppedUnstableKeywords(
                sort_keywords(dropped_unstable_keywords), pkg.commit, pkg=pkg)

    def rename_checks(self, pkgs):
        """Check for issues due to package modifications."""
        pkg = pkgs[0]
        old_key, new_key = pkg.old.key, pkg.key

        # same package, probably version bump and remove old
        if old_key == new_key:
            return

        pkgmoves = (
            x[1:] for x in self.repo.config.updates.get(old_key, ())
            if x[0] == 'move')

        for old, new in pkgmoves:
            if old.key == old_key and new.key == new_key:
                break
        else:
            yield MissingMove(old_key, new_key, pkg=pkg)

    def modified_checks(self, pkgs):
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

        if old_pkg.rdepend != new_pkg.rdepend:
            yield RdependChange(pkg=new_pkg)

        old_slot, new_slot = old_pkg.slot, new_pkg.slot
        if old_slot != new_slot:
            slotmoves = (
                x[1:] for x in self.repo.config.updates.get(new_pkg.key, ())
                if x[0] == 'slotmove')
            for atom, moved_slot in slotmoves:
                if atom.match(old_pkg) and new_slot == moved_slot:
                    break
            else:
                yield MissingSlotmove(old_slot, new_slot, pkg=new_pkg)

    def feed(self, pkgset):
        # Mapping of commit types to pkgs, available commit types can be seen
        # under the --diff-filter option in git log parsing support and are
        # disambiguated as follows:
        # A -> added, R -> renamed, M -> modified, D -> deleted
        pkg_map = {'A': set(), 'R': set(), 'M': set(), 'D': set()}
        # Iterate over pkg commits in chronological order (git log defaults to
        # the reverse) discarding matching pkg commits where relevant.
        for pkg in reversed(pkgset):
            pkg_map[pkg.status].add(pkg)
            if pkg.status == 'A':
                pkg_map['D'].discard(pkg)
            elif pkg.status == 'D':
                pkg_map['A'].discard(pkg)
            elif pkg.status == 'R':
                # create pkg add/removal for rename operation
                pkg_map['A'].add(pkg)
                pkg_map['D'].add(pkg.old_pkg())

        # run removed package checks
        if pkg_map['D']:
            yield from self.removal_checks(list(pkg_map['D']))
        # run renamed package checks
        if pkg_map['R']:
            yield from self.rename_checks(list(pkg_map['R']))
        # run modified package checks
        if modified := [pkg for pkg in pkg_map['M'] if pkg not in pkg_map['D']]:
            yield from self.modified_checks(modified)

        for git_pkg in pkgset:
            # remaining checks are irrelevant for removed packages
            if git_pkg in pkg_map['D']:
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
                year = mo.group('end')
                if int(year) != self.today.year:
                    yield EbuildIncorrectCopyright(year, line.strip('\n'), pkg=pkg)

            # checks for newly added ebuilds
            if git_pkg.status == 'A':
                # check for directly added stable ebuilds
                if pkg.category not in self.allowed_direct_stable:
                    if stable_keywords := sorted(x for x in pkg.keywords if x[0] not in '~-'):
                        yield DirectStableKeywords(stable_keywords, pkg=pkg)

                # pkg was just added to the tree
                newly_added = not self.added_repo.match(git_pkg.unversioned_atom)

                # check for no maintainers
                if not pkg.maintainers and newly_added:
                    yield DirectNoMaintainer(pkg=pkg)


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
        sign_offs = ', '.join(self.missing_sign_offs)
        return f'commit {self.commit}, missing sign-off{s}: {sign_offs}'


class InvalidCommitTag(results.CommitResult, results.Style):
    """Local commit has a tag that is incompliant.

    Commit tags have restrictions as to the allowed format and data
    used per GLEP 66 [#]_.

    .. [#] https://www.gentoo.org/glep/glep-0066.html#commit-messages
    """

    def __init__(self, tag, value, error, **kwargs):
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
        return f'commit {self.commit}: {self.error}'


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
        return f'commit {self.commit}, {self.error}: {self.summary!r}'


def verify_tags(*tags, required=False):
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
    known_results = frozenset([
        MissingSignOff, InvalidCommitTag, InvalidCommitMessage, BadCommitSummary,
    ])

    # mapping between known commit tags and verification methods
    known_tags = {}
    _commit_footer_regex = re.compile(r'^(?P<tag>[a-zA-Z0-9_-]+): (?P<value>.*)$')
    _git_cat_file_regex = re.compile(r'^(?P<object>.+?) (?P<status>.+)$')

    # categories exception for rule of having package version in summary
    skipped_categories = frozenset({
        'acct-group', 'acct-user', 'virtual',
    })

    def __init__(self, *args):
        super().__init__(*args)
        # mapping of required tags to forcibly run verifications methods
        self._required_tags = ImmutableDict(
            ((tag, verify), [])
            for tag, (verify, required) in self.known_tags.items() if required)

    @verify_tags('Signed-off-by', required=True)
    def _signed_off_by_tag(self, tag, values, commit):
        """Verify commit contains all required sign offs in accordance with GLEP 76."""
        required_sign_offs = {commit.author, commit.committer}
        missing_sign_offs = required_sign_offs.difference(values)
        if missing_sign_offs:
            yield MissingSignOff(sorted(missing_sign_offs), commit=commit)

    @verify_tags('Gentoo-Bug')
    def _deprecated_tag(self, tag, values, commit):
        """Flag deprecated tags that shouldn't be used."""
        for value in values:
            yield InvalidCommitTag(
                tag, value, f"{tag} tag is no longer valid", commit=commit)

    @verify_tags('Bug', 'Closes')
    def _bug_tag(self, tag, values, commit):
        """Verify values are URLs for Bug/Closes tags."""
        for value in values:
            parsed = urlparse(value)
            if not parsed.scheme:
                yield InvalidCommitTag(tag, value, "value isn't a URL", commit=commit)
                continue
            if parsed.scheme.lower() not in ("http", "https"):
                yield InvalidCommitTag(
                    tag, value, "invalid protocol; should be http or https", commit=commit)

    @klass.jit_attr_none
    def git_cat_file(self):
        """Start a `git cat-file` process to verify git repo hashes."""
        return subprocess.Popen(
            ['git', 'cat-file', '--batch-check'],
            cwd=self.options.target_repo.location,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            encoding='utf8', bufsize=1)

    @verify_tags('Fixes', 'Reverts')
    def _commit_tag(self, tag, values, commit):
        """Verify referenced commits exist for Fixes/Reverts tags."""
        self.git_cat_file.stdin.write('\n'.join(values) + '\n')
        if self.git_cat_file.poll() is None:
            for _ in range(len(values)):
                line = self.git_cat_file.stdout.readline().strip()
                if mo := self._git_cat_file_regex.match(line):
                    value = mo.group('object')
                    status = mo.group('status')
                    if not status.startswith('commit '):
                        yield InvalidCommitTag(
                            tag, value, f'{status} commit', commit=commit)

    def feed(self, commit):
        if len(commit.message) == 0:
            yield InvalidCommitMessage('no commit message', commit=commit)
            return

        # drop leading '*: ' prefix assuming it's a package/eclass/file/path
        summary = commit.message[0]
        if len(summary.split(': ', 1)[-1]) > 69:
            yield InvalidCommitMessage('summary is too long', commit=commit)

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
                if not re.match(rf'^{re.escape(atom.key)}: ', summary):
                    error = f'summary missing {atom.key!r} package prefix'
                    yield BadCommitSummary(error, summary, commit=commit)
                # check for version in summary for singular, non-revision bumps
                if len(commit.pkgs['A']) == 1 and category not in self.skipped_categories:
                    atom = next(iter(commit.pkgs['A']))
                    if not atom.revision and not re.match(rf'^.+\bv?{re.escape(atom.version)}\b.*$', summary):
                        error = f'summary missing package version {atom.version!r}'
                        yield BadCommitSummary(error, summary, commit=commit)
            else:
                # mutiple pkg changes in the same category
                if not re.match(rf'^{re.escape(category)}: ', summary):
                    error = f'summary missing {category!r} category prefix'
                    yield BadCommitSummary(error, summary, commit=commit)

        # verify message body
        i = iter(commit.message[1:])
        lineno = 1
        body = False
        for lineno, line in enumerate(i, lineno):
            if not line.strip():
                continue
            if self._commit_footer_regex.match(line) is None:
                if not body and commit.message[1] != '':
                    yield InvalidCommitMessage(
                        'missing empty line before body', commit=commit)
                # still processing the body
                body = True
                if len(line.split()) > 1 and len(line) > 80:
                    yield InvalidCommitMessage(
                        f'line {lineno} greater than 80 chars: {line!r}', commit=commit)
            else:
                if commit.message[lineno - 1] != '':
                    yield InvalidCommitMessage(
                        'missing empty line before tags', commit=commit)
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
                    yield InvalidCommitMessage(
                        f'empty line {lineno} in footer', commit=commit)
                continue
            if mo := self._commit_footer_regex.match(line):
                # register known tags for verification
                tag = mo.group('tag')
                try:
                    func, required = self.known_tags[tag]
                    tags.setdefault((tag, func), []).append(mo.group('value'))
                except KeyError:
                    continue
            else:
                yield InvalidCommitMessage(
                    f'non-tag in footer, line {lineno}: {line!r}', commit=commit)

        # run tag verification methods
        for (tag, func), values in tags.items():
            yield from func(self, tag, values, commit)


class EclassIncorrectCopyright(IncorrectCopyright, results.EclassResult):
    """Changed eclass with incorrect copyright date."""

    @property
    def desc(self):
        return f'{self.eclass}: {super().desc}'


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
            year = mo.group('end')
            if int(year) != self.today.year:
                yield EclassIncorrectCopyright(year, line.strip('\n'), eclass=eclass)
