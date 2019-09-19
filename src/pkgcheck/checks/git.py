import os
import subprocess
import tarfile
from datetime import datetime
from itertools import chain
from tempfile import TemporaryDirectory

from pkgcore.ebuild.misc import sort_keywords
from pkgcore.ebuild.repository import UnconfiguredTree
from pkgcore.exceptions import PkgcoreException
from snakeoil.demandload import demand_compile_regexp
from snakeoil.klass import jit_attr
from snakeoil.osutils import pjoin
from snakeoil.strings import pluralism as _pl

from .. import addons, base, sources
from ..log import logger

demand_compile_regexp(
    'ebuild_copyright_regex',
    r'^# Copyright (\d\d\d\d(-\d\d\d\d)?) .+')


class OutdatedCopyright(base.VersionedResult, base.Warning):
    """Changed ebuild with outdated copyright."""

    def __init__(self, year, line, **kwargs):
        super().__init__(**kwargs)
        self.year = year
        self.line = line

    @property
    def desc(self):
        return f'outdated copyright year {self.year!r}: {self.line!r}'


class BadCommitSummary(base.PackageResult, base.Warning):
    """Local package commit with poorly formatted or unmatching commit summary.

    Git commit messages for packages should be formatted in the standardized
    fashion described in the devmanual [#]_. Specifically, the
    ``${CATEGORY}/${PN}:`` prefix should be used in the summary relating to
    the modified package.

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


class DirectStableKeywords(base.VersionedResult, base.Error):
    """Newly committed ebuild with stable keywords."""

    def __init__(self, keywords, **kwargs):
        super().__init__(**kwargs)
        self.keywords = tuple(keywords)

    @property
    def desc(self):
        return f'directly committed with stable keyword%s: [ %s ]' % (
            _pl(self.keywords), ', '.join(self.keywords))


class DroppedUnstableKeywords(base.PackageResult, base.Warning):
    """Unstable keywords dropped from package."""

    status = 'unstable'

    def __init__(self, keywords, commit, **kwargs):
        super().__init__(**kwargs)
        self.keywords = tuple(keywords)
        self.commit = commit

    @property
    def desc(self):
        keywords = ', '.join(self.keywords)
        return (
            f"commit {self.commit} (or later) dropped {self.status} "
            f"keyword{_pl(self.keywords)}: [ {keywords} ]"
        )


class DroppedStableKeywords(base.Error, DroppedUnstableKeywords):
    """Stable keywords dropped from package."""

    status = 'stable'


class DirectNoMaintainer(base.PackageResult, base.Error):
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


class GitPkgCommitsCheck(base.GentooRepoCheck):
    """Check unpushed git package commits for various issues."""

    feed_type = base.package_feed
    scope = base.package_scope
    source = sources.GitCommitsRepoSource
    required_addons = (addons.GitAddon,)
    known_results = (
        DirectStableKeywords, DirectNoMaintainer, BadCommitSummary,
        OutdatedCopyright, DroppedStableKeywords, DroppedUnstableKeywords,
    )

    def __init__(self, options, git_addon):
        super().__init__(options)
        self.today = datetime.today()
        self.repo = self.options.target_repo
        self.valid_arches = self.options.target_repo.known_arches
        self.added_repo = git_addon.commits_repo(addons.GitAddedRepo)

    @jit_attr
    def removal_repo(self):
        """Create a repository of packages removed from git."""
        return _RemovalRepo(self.repo)

    def removal_checks(self, removed):
        """Check for issues due to package removals."""
        pkg = removed[0]
        commit = removed[0].commit

        try:
            removal_repo = self.removal_repo(removed)
        except PkgcoreException as e:
            logger.warning(f'skipping git removal checks: {e}')
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
            if not summary.startswith(f'{git_pkg.unversioned_atom}: '):
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
                added_pkgs = self.added_repo.match(git_pkg.unversioned_atom)
                newly_added = all(x.date == added_pkgs[0].date for x in added_pkgs)

                # check for no maintainers
                if newly_added and not pkg.maintainers:
                    yield DirectNoMaintainer(pkg=pkg)


class MissingSignOff(base.CommitResult, base.Error):
    """Local commit with missing sign offs.

    Sign offs are required for commits as specified by GLEP 76 [#]_.

    .. [#] https://www.gentoo.org/glep/glep-0076.html#certificate-of-origin
    """

    def __init__(self, missing_sign_offs, **kwargs):
        super().__init__(**kwargs)
        self.missing_sign_offs = missing_sign_offs

    @property
    def desc(self):
        sign_offs = ', '.join(self.missing_sign_offs)
        return (
            f'commit {self.commit}, '
            f'missing sign-off{_pl(self.missing_sign_offs)}: {sign_offs}'
        )


class GitCommitsCheck(base.GentooRepoCheck, base.ExplicitlyEnabledCheck):
    """Check unpushed git commits for various issues."""

    feed_type = base.commit_feed
    scope = base.commit_scope
    source = sources.GitCommitsSource
    known_results = (MissingSignOff,)

    def feed(self, commit):
        # check for missing git sign offs
        sign_offs = {
            line[15:].strip() for line in commit.message
            if line.startswith('Signed-off-by: ')}
        required_sign_offs = {commit.author, commit.committer}
        missing_sign_offs = required_sign_offs - sign_offs
        if missing_sign_offs:
            yield MissingSignOff(tuple(sorted(missing_sign_offs)), commit=commit)
