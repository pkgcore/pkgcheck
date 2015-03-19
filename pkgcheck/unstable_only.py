# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: BSD/GPL2

from pkgcore.restrictions import packages, values

from pkgcheck.addons import ArchesAddon, StableCheckAddon
from pkgcheck.base import package_feed, Result


class UnstableOnly(Result):

    """package/keywords that are strictly unstable"""

    __slots__ = ("category", "package", "version", "arch")

    threshold = package_feed

    def __init__(self, pkgs, arch):
        Result.__init__(self)
        self._store_cp(pkgs[0])
        self.arch = arch
        self.version = tuple(x.fullver for x in pkgs)

    @property
    def short_desc(self):
        return "for arch %s, all versions are unstable: [ %s ]" % (
            self.arch, ', '.join(self.version))


class UnstableOnlyReport(StableCheckAddon):
    """scan for pkgs that have just unstable keywords"""

    feed_type = package_feed
    required_addons = (ArchesAddon,)
    known_results = (UnstableOnly,)

    def __init__(self, options, arches, *args):
        super(UnstableOnlyReport, self).__init__(options)
        arches = set(x.strip().lstrip("~") for x in self.arches)

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
        for k, v in self.arch_restricts.iteritems():
            stable = unstable = None
            for x in pkgset:
                if v[0].match(x):
                    stable = x
                    break
            if stable is not None:
                continue
            unstable = [x for x in pkgset if v[1].match(x)]
            if unstable:
                reporter.add_report(UnstableOnly(unstable, k))

    def finish(self, reporter):
        self.arch_restricts.clear()
