import os
import re
import subprocess
import tarfile
from collections import defaultdict
from datetime import datetime
from itertools import chain
from tempfile import TemporaryDirectory
from urllib.parse import urlparse

from pkgcore.ebuild.misc import sort_keywords
from pkgcore.ebuild.repository import UnconfiguredTree
from pkgcore.exceptions import PkgcoreException
from snakeoil.decorators import coroutine
from snakeoil.demandload import demand_compile_regexp
from snakeoil.klass import jit_attr
from snakeoil.osutils import pjoin
from snakeoil.strings import pluralism

from .. import base, git, results, sources
from ..log import logger
from . import ExplicitlyEnabledCheck, GentooRepoCheck

demand_compile_regexp(
    'ebuild_copyright_regex',
    r'^# Copyright (\d\d\d\d(-\d\d\d\d)?) .+')

demand_compile_regexp(
    'commit_footer',
    r'^(?P<tag>[a-zA-Z0-9_-]+): (?P<value>.*)$')

demand_compile_regexp(
    'git_cat_file_regex',
    r'^(?P<object>.+?) (?P<status>.+)$')


class GitCommitsRepoSource(sources.RepoSource):
    """Repository source for locally changed packages in git history.

    Parses git log history to determine packages with changes that
    haven't been pushed upstream yet.
    """

    required_addons = (git.GitAddon,)

    def __init__(self, *args, git_addon):
        super().__init__(*args)
        self._repo = git_addon.commits_repo(git.GitChangedRepo)


class GitCommitsSource(sources.Source):
    """Source for local commits in git history.

    Parses git log history to determine commits that haven't been pushed
    upstream yet.
    """

    feed_type = base.commit_scope
    required_addons = (git.GitAddon,)

    def __init__(self, *args, git_addon):
        super().__init__(*args, source=git_addon.commits())


class OutdatedCopyright(results.VersionResult, results.Warning):
    """Changed ebuild with outdated copyright."""

    def __init__(self, year, line, **kwargs):
        super().__init__(**kwargs)
        self.year = year
        self.line = line

    @property
    def desc(self):
        return f'outdated copyright year {self.year!r}: {self.line!r}'


class BadCommitSummary(results.PackageResult, results.Warning):
    """Local package commit with poorly formatted or unmatching commit summary.

    Git commit messages for packages should be formatted in the standardized
    fashion described in the devmanual [#]_. Specifically, a
    ``${CATEGORY}/${PN}:`` or ``${CATEGORY}/${P}:`` prefix should be used in
    the summary relating to the modified package.

    .. [#] https://devmanual.gentoo.org/ebuild-maintenance/git/#git-commit-message-format
    """

    def __init__(self, error, summary, commit, **kwargs):
        super().__init__(**kwargs)
        self.error = error
        self.summary = summary
        self.commit = commit

    @property
    def desc(self):
        return f'commit {self.commit}, {self.error}: {self.summary!r}'


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
        self.commit = commit

    @property
    def desc(self):
        s = pluralism(self.keywords)
        keywords = ', '.join(self.keywords)
        return (
            f'commit {self.commit} (or later) dropped {self._status} '
            f'keyword{s}: [ {keywords} ]'
        )


class DroppedUnstableKeywords(_DroppedKeywords, results.Warning):
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


class _RemovalRepo(UnconfiguredTree):
    """Repository of removed packages stored in a temporary directory."""

    def __init__(self, repo):
        self.__parent_repo = repo
        self.__tmpdir = TemporaryDirectory()
        self.__created = False
        repo_dir = self.__tmpdir.name

        # set up some basic repo files so pkgcore doesn't complain
        os.makedirs(pjoin(repo_dir, 'metadata'))
        with open(pjoin(repo_dir, 'metadata', 'layout.conf'), 'w') as f:
            f.write('masters =\n')
        os.makedirs(pjoin(repo_dir, 'profiles'))
        with open(pjoin(repo_dir, 'profiles', 'repo_name'), 'w') as f:
            f.write('old-repo\n')
        super().__init__(repo_dir)

    def __call__(self, pkgs):
        """Update the repo with a given sequence of packages."""
        self._populate(pkgs, eclasses=(not self.__created))
        if self.__created:
            # notify the repo object that new pkgs were added
            for pkg in pkgs:
                self.notify_add_package(pkg)
        self.__created = True
        return self

    def _populate(self, pkgs, eclasses=False):
        """Populate the repo with a given sequence of historical packages."""
        pkg = pkgs[0]
        commit = pkgs[0].commit

        paths = [pjoin(pkg.category, pkg.package)]
        if eclasses:
            paths.append('eclass')
        git_cmd = f"git archive {commit}~1 {' '.join(paths)}"

        old_files = subprocess.Popen(
            git_cmd.split(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=self.__parent_repo.location)
        with tarfile.open(mode='r|', fileobj=old_files.stdout) as tar:
            tar.extractall(path=self.location)
        if old_files.poll():
            error = old_files.stderr.read().decode().strip()
            raise PkgcoreException(error)

    def __del__(self):
        self.__tmpdir.cleanup()


class GitPkgCommitsCheck(GentooRepoCheck):
    """Check unpushed git package commits for various issues."""

    scope = base.package_scope
    _source = (sources.PackageRepoSource, (), (('source', GitCommitsRepoSource),))
    required_addons = (git.GitAddon,)
    known_results = frozenset([
        DirectStableKeywords, DirectNoMaintainer, BadCommitSummary,
        OutdatedCopyright, DroppedStableKeywords, DroppedUnstableKeywords,
    ])

    def __init__(self, *args, git_addon):
        super().__init__(*args)
        self.today = datetime.today()
        self.repo = self.options.target_repo
        self.valid_arches = self.options.target_repo.known_arches
        self._git_addon = git_addon

    @jit_attr
    def removal_repo(self):
        """Create a repository of packages removed from git."""
        return _RemovalRepo(self.repo)

    @jit_attr
    def added_repo(self):
        """Create/load cached repo of packages added to git."""
        return self._git_addon.cached_repo(git.GitAddedRepo)

    def removal_checks(self, removed):
        """Check for issues due to package removals."""
        pkg = removed[0]
        commit = removed[0].commit

        try:
            removal_repo = self.removal_repo(removed)
        except PkgcoreException as e:
            logger.warning('skipping git removal checks: %s', e)
            return

        old_keywords = set(chain.from_iterable(
            pkg.keywords for pkg in removal_repo.match(pkg.unversioned_atom)))
        new_keywords = set(chain.from_iterable(
            pkg.keywords for pkg in self.repo.match(pkg.unversioned_atom)))

        dropped_keywords = old_keywords - new_keywords
        dropped_stable_keywords = dropped_keywords & self.valid_arches
        dropped_unstable_keywords = set()
        for keyword in (x for x in dropped_keywords if x[0] == '~'):
            arch = keyword[1:]
            if arch in self.valid_arches and arch not in new_keywords:
                dropped_unstable_keywords.add(keyword)

        if dropped_stable_keywords:
            yield DroppedStableKeywords(
                sort_keywords(dropped_stable_keywords), commit, pkg=pkg)
        if dropped_unstable_keywords:
            yield DroppedUnstableKeywords(
                sort_keywords(dropped_unstable_keywords), commit, pkg=pkg)

    def feed(self, pkgset):
        removed = [pkg for pkg in pkgset if pkg.status == 'D']
        if removed:
            yield from self.removal_checks(removed)

        for git_pkg in pkgset:
            # check git commit summary formatting
            try:
                summary = git_pkg.message[0]
            except IndexError:
                summary = ''
            summary_prefix_re = rf'^({git_pkg.key}|{git_pkg.cpvstr}): '
            if not re.match(summary_prefix_re, summary):
                error = 'summary missing matching package prefix'
                yield BadCommitSummary(error, summary, git_pkg.commit, pkg=git_pkg)

            try:
                pkg = self.repo.match(git_pkg.versioned_atom)[0]
            except IndexError:
                # weird situation where an ebuild was locally committed and then removed
                return

            # check copyright on new/modified ebuilds
            try:
                line = next(pkg.ebuild.text_fileobj())
            except StopIteration:
                # empty ebuild, should be caught by other checks
                return
            copyright = ebuild_copyright_regex.match(line)
            if copyright:
                year = copyright.group(1).split('-')[-1]
                if int(year) < self.today.year:
                    yield OutdatedCopyright(year, line.strip('\n'), pkg=pkg)

            # checks for newly added ebuilds
            if git_pkg.status == 'A':
                # check for stable keywords
                stable_keywords = sorted(x for x in pkg.keywords if x[0] not in '~-')
                if stable_keywords:
                    yield DirectStableKeywords(stable_keywords, pkg=pkg)

                # pkg was just added to the tree
                newly_added = not self.added_repo.match(git_pkg.unversioned_atom)

                # check for no maintainers
                if not pkg.maintainers and newly_added:
                    yield DirectNoMaintainer(pkg=pkg)


class MissingSignOff(results.CommitResult, results.Error):
    """Local commit with missing sign offs.

    Sign offs are required for commits as specified by GLEP 76 [#]_.

    .. [#] https://www.gentoo.org/glep/glep-0076.html#certificate-of-origin
    """

    def __init__(self, missing_sign_offs, **kwargs):
        super().__init__(**kwargs)
        self.missing_sign_offs = missing_sign_offs

    @property
    def desc(self):
        s = pluralism(self.missing_sign_offs)
        sign_offs = ', '.join(self.missing_sign_offs)
        return f'commit {self.commit}, missing sign-off{s}: {sign_offs}'


class InvalidCommitTag(results.CommitResult, results.Warning):
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


class InvalidCommitMessage(results.CommitResult, results.Warning):
    """Local commit has issues with its commit message."""

    def __init__(self, error, **kwargs):
        super().__init__(**kwargs)
        self.error = error

    @property
    def desc(self):
        return f'commit {self.commit}: {self.error}'


# mapping between known commit tags and verification methods
_known_tags = {}


def verify_tags(*tags, required=False):
    """Decorator to register commit tag verification methods."""
    def wrapper(func):
        for tag in tags:
            _known_tags[tag] = (func, required)
    return wrapper


class GitCommitsCheck(GentooRepoCheck, ExplicitlyEnabledCheck):
    """Check unpushed git commits for various issues."""

    scope = base.commit_scope
    _source = GitCommitsSource
    known_results = frozenset([MissingSignOff, InvalidCommitTag, InvalidCommitMessage])

    @verify_tags('Signed-off-by', required=True)
    @coroutine
    def _signed_off_by_tag(self):
        while True:
            results = []
            tag, values, commit = (yield)
            required_sign_offs = {commit.author, commit.committer}
            missing_sign_offs = required_sign_offs.difference(values)
            if missing_sign_offs:
                results.append(MissingSignOff(tuple(sorted(missing_sign_offs)), commit=commit))
            yield results

    @verify_tags('Gentoo-Bug')
    @coroutine
    def _deprecated_tag(self):
        while True:
            results = []
            tag, values, commit = (yield)
            for value in values:
                results.append(InvalidCommitTag(
                    tag, value,
                    f"{tag} tag is no longer valid",
                    commit=commit))
            yield results

    @verify_tags('Bug', 'Closes')
    @coroutine
    def _bug_tag(self):
        while True:
            results = []
            tag, values, commit = (yield)
            for value in values:
                parsed = urlparse(value)
                if not parsed.scheme:
                    results.append(
                        InvalidCommitTag(tag, value, "value isn't a URL", commit=commit))
                    continue
                if parsed.scheme.lower() not in ("http", "https"):
                    results.append(InvalidCommitTag(
                        tag, value,
                        "invalid protocol; should be http or https",
                        commit=commit))
            yield results

    @verify_tags('Fixes', 'Reverts')
    @coroutine
    def _commit_tag(self):
        while True:
            results = []
            tag, values, commit = (yield)
            p = subprocess.run(
                ['git', 'cat-file', '--batch-check'],
                cwd=self.options.target_repo.location,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                input='\n'.join(values), encoding='utf8')
            if p.returncode == 0:
                for line in p.stdout.splitlines():
                    m = git_cat_file_regex.match(line)
                    if m is not None:
                        value = m.group('object')
                        status = m.group('status')
                        if not status.startswith('commit '):
                            results.append(InvalidCommitTag(
                                tag, value, f'{status} commit', commit=commit))
            yield results

    def feed(self, commit):
        if len(commit.message) == 0:
            yield InvalidCommitMessage("no commit message", commit=commit)
            return

        # drop leading '*: ' prefix assuming it's a package/eclass/file/path
        summary = commit.message[0]
        if len(summary.split(': ', 1)[-1]) > 69:
            yield InvalidCommitMessage("summary is too long", commit=commit)

        # verify message body
        i = iter(commit.message[1:])
        for line in i:
            if not line:
                continue
            m = commit_footer.match(line)
            if m is None:
                # still processing the body
                if len(line.split()) > 1 and len(line) > 80:
                    yield InvalidCommitMessage(
                        f"line greater than 80 chars: {line!r}",
                        commit=commit)
            else:
                # push it back on the stack
                i = chain([line], i)
                break

        # mapping of defined tags to any existing verification methods
        tag_mapping = defaultdict(list)
        # forcibly run verifications methods for required tags
        tag_mapping.update(
            ((tag, verify), [])
            for tag, (verify, required) in _known_tags.items() if required)

        # verify footer
        for line in i:
            if not line:
                yield InvalidCommitMessage(
                    "there should not be newlines between footer blocks",
                    commit=commit)
                continue
            m = commit_footer.match(line)
            if m is None:
                yield InvalidCommitMessage(
                    f"non-footer line in footer: {line!r}",
                    commit=commit)
            else:
                # register known tags for verification
                tag = m.group('tag')
                try:
                    verify, required = _known_tags[tag]
                    tag_mapping[(tag, verify)].append(m.group('value'))
                except KeyError:
                    continue

        # run tag verification methods
        for (tag, coro), values in tag_mapping.items():
            yield from coro(self).send((tag, values, commit))
