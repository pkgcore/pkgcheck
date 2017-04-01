from collections import defaultdict

from pkgcore.restrictions import packages, values
from snakeoil.strings import pluralism

from pkgcheck.addons import ArchesAddon, StableCheckAddon
from pkgcheck.base import package_feed, Warning


class UnstableOnly(Warning):
    """package/keywords that are strictly unstable"""

    __slots__ = ("category", "package", "versions", "arches")

    threshold = package_feed

    def __init__(self, pkgs, arches):
        super(UnstableOnly, self).__init__()
        self._store_cp(pkgs[0])
        self.arches = arches
        self.versions = tuple(x.fullver for x in pkgs)

    @property
    def short_desc(self):
        return "for arch%s: [ %s ], all versions are unstable: [ %s ]" % (
            pluralism(self.arches, plural='es'), ', '.join(self.arches), ', '.join(self.versions))


class UnstableOnlyReport(StableCheckAddon):
    """scan for pkgs that have just unstable keywords"""

    feed_type = package_feed
    required_addons = (ArchesAddon,)
    known_results = (UnstableOnly,)

    def __init__(self, options, arches):
        super(UnstableOnlyReport, self).__init__(options)
        arches = set(x.strip().lstrip("~") for x in options.arches)

        # stable, then unstable, then file
        self.arch_restricts = {}
        for arch in arches:
            self.arch_restricts[arch] = [
                packages.PackageRestriction(
                    "keywords", values.ContainmentMatch(arch)),
                packages.PackageRestriction(
                    "keywords", values.ContainmentMatch("~%s" % arch))
            ]

    def feed(self, pkgset, reporter):
        # stable, then unstable, then file
        unstable_arches = defaultdict(list)
        for k, v in self.arch_restricts.iteritems():
            stable = unstable = None
            for x in pkgset:
                if v[0].match(x):
                    stable = x
                    break
            if stable is not None:
                continue
            unstable = tuple(x for x in pkgset if v[1].match(x))
            if unstable:
                unstable_arches[unstable].append(k)

        # collapse reports by available versions
        for pkgs in unstable_arches.iterkeys():
            reporter.add_report(UnstableOnly(pkgs, unstable_arches[pkgs]))

    def finish(self, reporter):
        self.arch_restricts.clear()
