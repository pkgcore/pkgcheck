from datetime import datetime

from snakeoil.demandload import demand_compile_regexp
from snakeoil.strings import pluralism as _pl

from .. import addons, base

demand_compile_regexp(
    'ebuild_copyright_regex',
    r'^# Copyright (\d\d\d\d(-\d\d\d\d)?) .+')
demand_compile_regexp(
    'old_gentoo_copyright_regex',
    r'^# Copyright (\d\d\d\d(-\d\d\d\d)?) Gentoo Foundation')


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


class OldGentooCopyright(base.Warning):
    """Changed ebuild with old Gentoo copyright.

    Previously ebuilds assigned copyright to the Gentoo Foundation by default.
    Now that's been changed to Gentoo Authors in GLEP 76.
    """

    __slots__ = ('category', 'package', 'version', 'line')
    threshold = base.versioned_feed

    def __init__(self, pkg, line):
        super().__init__()
        self._store_cpv(pkg)
        self.line = line

    @property
    def short_desc(self):
        return f'old copyright, update to "Gentoo Authors": {self.line!r}'


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


class GitCommitsCheck(base.DefaultRepoCheck):
    """Check unpushed git commits for various issues."""

    feed_type = base.package_feed
    filter_type = base.git_filter
    required_addons = (addons.GitAddon,)
    known_results = (
        DirectStableKeywords, DirectNoMaintainer,
        InvalidCopyright, OutdatedCopyright, OldGentooCopyright,
    )

    def __init__(self, options, git_addon):
        super().__init__(options)
        self.today = datetime.today()
        self.added_repo = git_addon.commits_repo(addons.GitAddedRepo)

    def feed(self, pkgset):
        for git_pkg in pkgset:
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
                    yield OutdatedCopyright(pkg, year, line.strip('\n'))
                if old_gentoo_copyright_regex.match(line):
                    yield OldGentooCopyright(pkg, line.strip('\n'))
            else:
                yield InvalidCopyright(pkg, line.strip('\n'))

            # checks for newly added ebuilds
            if git_pkg.status == 'A':
                # check for stable keywords
                stable_keywords = sorted(x for x in pkg.keywords if x[0] not in '~-')
                if stable_keywords:
                    yield DirectStableKeywords(pkg, stable_keywords)

                # pkg was just added to the tree
                added_pkgs = self.added_repo.match(git_pkg.unversioned_atom)
                newly_added = all(x.date == added_pkgs[0].date for x in added_pkgs)

                # check for no maintainers
                if newly_added and not pkg.maintainers:
                    yield DirectNoMaintainer(pkg)
