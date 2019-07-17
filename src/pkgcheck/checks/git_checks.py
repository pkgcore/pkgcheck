from datetime import datetime

from snakeoil.demandload import demand_compile_regexp
from snakeoil.strings import pluralism as _pl

from .. import addons, base

demand_compile_regexp(
    'ebuild_copyright_regex',
    r'^# Copyright (\d\d\d\d(-\d\d\d\d)?) .+')


class InvalidCopyright(base.Warning):
    """Changed ebuild with invalid copyright."""

    __slots__ = ('category', 'package', 'version', 'line')
    threshold = base.versioned_feed

    def __init__(self, pkg, line):
        super().__init__()
        self._store_cpv(pkg)
        self.line = line

    @property
    def short_desc(self):
        return f'invalid copyright: {self.line!r}'


class OutdatedCopyright(base.Warning):
    """Changed ebuild with outdated copyright."""

    __slots__ = ('category', 'package', 'version', 'year', 'line')
    threshold = base.versioned_feed

    def __init__(self, pkg, year, line):
        super().__init__()
        self._store_cpv(pkg)
        self.year = year
        self.line = line

    @property
    def short_desc(self):
        return f'outdated copyright year {self.year!r}: {self.line!r}'


class DirectStableKeywords(base.Error):
    """Newly committed ebuild with stable keywords."""

    __slots__ = ('category', 'package', 'version', 'keywords')
    threshold = base.versioned_feed

    def __init__(self, pkg, keywords):
        super().__init__()
        self._store_cpv(pkg)
        self.keywords = tuple(keywords)

    @property
    def short_desc(self):
        return f'directly committed with stable keyword%s: [ %s ]' % (
            _pl(self.keywords), ', '.join(self.keywords))


class DirectNoMaintainer(base.Error):
    """Directly added, new package with no specified maintainer."""

    __slots__ = ('category', 'package')
    threshold = base.package_feed

    def __init__(self, pkg):
        super().__init__()
        self._store_cp(pkg)

    @property
    def short_desc(self):
        return 'directly committed with no package maintainer'


class GitCommitsCheck(base.Template):
    """Check unpushed git commits for various issues."""

    feed_type = base.package_feed
    filter_type = base.git_filter
    required_addons = (addons.GitAddon,)
    known_results = (
        DirectStableKeywords, DirectNoMaintainer, InvalidCopyright, OutdatedCopyright,
    )

    def __init__(self, options, git_addon):
        super().__init__(options)
        self.today = datetime.today()
        self.added_repo = git_addon.commits_repo(addons.GitAddedRepo)

    def feed(self, pkgset, reporter):
        invalid_copyrights = set()
        outdated_copyrights = set()

        for git_pkg in pkgset:
            if self.options.target_repo.repo_id == 'gentoo':
                try:
                    pkg = self.options.target_repo.match(git_pkg.versioned_atom)[0]
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
                        outdated_copyrights.add((pkg, year, line))
                else:
                    invalid_copyrights.add((pkg, line))

                # checks for newly added ebuilds
                if git_pkg.status == 'A':
                    # check for stable keywords
                    stable_keywords = sorted(x for x in pkg.keywords if x[0] not in '~-')
                    if stable_keywords:
                        reporter.add_report(DirectStableKeywords(pkg, stable_keywords))

                    # pkg was just added to the tree
                    added_pkgs = self.added_repo.match(git_pkg.unversioned_atom)
                    newly_added = all(x.date == added_pkgs[0].date for x in added_pkgs)

                    # check for no maintainers
                    if newly_added and not pkg.maintainers:
                        reporter.add_report(DirectNoMaintainer(pkg))

        for pkg, line in invalid_copyrights:
            reporter.add_report(InvalidCopyright(pkg, line.strip('\n')))
        for pkg, year, line in outdated_copyrights:
            reporter.add_report(OutdatedCopyright(pkg, year, line.strip('\n')))
