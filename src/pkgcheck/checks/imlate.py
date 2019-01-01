from pkgcore.restrictions import packages, values
from snakeoil.strings import pluralism as _pl

from .. import addons, base


class LaggingStable(base.Warning):
    """Arch that is behind another from a stabling standpoint."""

    __slots__ = ("category", "package", "version", "keywords", "stable")
    threshold = base.versioned_feed

    def __init__(self, pkg, keywords):
        super().__init__()
        self._store_cpv(pkg)
        self.keywords = tuple(sorted(keywords))
        self.stable = tuple(sorted(str(arch) for arch in pkg.keywords
                            if not arch[0] in ("~", "-")))

    @property
    def short_desc(self):
        return "stabled arch%s: [ %s ], potential%s: [ %s ]" % (
            _pl(self.stable, plural='es'), ', '.join(self.stable),
            _pl(self.keywords), ', '.join(self.keywords))


class ImlateReport(base.Template):
    """Scan for ebuilds that are lagging in stabilization."""

    feed_type = base.package_feed
    required_addons = (addons.StableArchesAddon,)
    known_results = (LaggingStable,)

    @staticmethod
    def mangle_argparser(parser):
        parser.plugin.add_argument(
            "--source-arches", action='csv', metavar='ARCH',
            help="comma separated list of arches to compare against for lagging stabilization",
            docs="""
                Comma separated list of arches to compare against for
                lagging stabilization.

                The default arches are all stable arches (unless --arches is specified).
            """)

    def __init__(self, options, stable_arches=None):
        super().__init__(options)
        arches = frozenset(arch.strip().lstrip("~") for arch in options.stable_arches)
        self.target_arches = frozenset(
            "~%s" % arch.strip().lstrip("~") for arch in arches)

        source_arches = options.source_arches
        if source_arches is None:
            source_arches = options.stable_arches
        self.source_arches = frozenset(
            arch.lstrip("~") for arch in source_arches)
        self.source_filter = packages.PackageRestriction(
            "keywords", values.ContainmentMatch2(self.source_arches))

    def feed(self, pkgset, reporter):
        fmatch = self.source_filter.match
        remaining = set(self.target_arches)
        for pkg in reversed(pkgset):
            if not fmatch(pkg):
                continue
            unstable_keys = remaining.intersection(pkg.keywords)
            if unstable_keys:
                reporter.add_report(LaggingStable(pkg, unstable_keys))
                remaining.difference_update(unstable_keys)
                if not remaining:
                    break
