# Copyright: 2006 Brian Harring <ferringb@gmail.com>

from pkgcore.restrictions import packages, values

from pkgcheck.addons import ArchesAddon, StableCheckAddon
from pkgcheck.base import versioned_feed, package_feed, Warning


class LaggingStable(Warning):
    """Arch that is behind another from a stabling standpoint."""

    __slots__ = ("category", "package", "version", "keywords", "stable")
    threshold = versioned_feed

    def __init__(self, pkg, keywords):
        super(LaggingStable, self).__init__()
        self._store_cpv(pkg)
        self.keywords = keywords
        self.stable = tuple(str(arch) for arch in pkg.keywords
                            if not arch[0] in ("~", "-"))

    @property
    def short_desc(self):
        return "stabled arches [ %s ], potentials [ %s ]" % \
            (', '.join(self.stable), ', '.join(self.keywords))


class ImlateReport(StableCheckAddon):
    """Scan for ebuilds that are lagging in stabilization."""

    feed_type = package_feed
    required_addons = (ArchesAddon,)
    known_results = (LaggingStable,)

    @staticmethod
    def mangle_argparser(parser):
        parser.plugin.add_argument(
            "--source-arches", action='extend_comma', metavar='ARCH',
            help="comma separated list of arches to compare against for lagging stabilization",
            docs="""
                Comma separated list of arches to compare against for
                lagging stabilization.

                The default arches are all stable arches (unless --arches is specified).
            """)

    def __init__(self, options, arches):
        super(ImlateReport, self).__init__(options)
        arches = frozenset(arch.strip().lstrip("~") for arch in options.arches)
        self.target_arches = frozenset(
            "~%s" % arch.strip().lstrip("~") for arch in arches)

        source_arches = options.source_arches
        if source_arches is None:
            source_arches = options.arches
        self.source_arches = frozenset(
            arch.lstrip("~") for arch in source_arches)
        self.source_filter = packages.PackageRestriction(
            "keywords", values.ContainmentMatch(*self.source_arches))

    def feed(self, pkgset, reporter):
        fmatch = self.source_filter.match
        remaining = set(self.target_arches)
        for pkg in reversed(pkgset):
            if not fmatch(pkg):
                continue
            unstable_keys = remaining.intersection(pkg.keywords)
            if unstable_keys:
                reporter.add_report(LaggingStable(pkg, sorted(unstable_keys)))
                remaining.difference_update(unstable_keys)
                if not remaining:
                    break
