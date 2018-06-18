from collections import defaultdict
from itertools import chain
import time

from snakeoil.strings import pluralism

from pkgcheck import addons, base

day = 24*3600


class StaleUnstable(base.Warning):
    """Packages with unstable keywords over a month old."""

    __slots__ = ("category", "package", "version", "keywords", "period")

    threshold = base.versioned_feed

    def __init__(self, pkg, keywords, period):
        super(StaleUnstable, self).__init__()
        self._store_cpv(pkg)
        self.slot = pkg.slot
        self.keywords = tuple(sorted(keywords))
        self.period = period

    @property
    def short_desc(self):
        return "slot(%s) no change in %i days for unstable keyword%s: [ %s ]" % (
            self.slot, self.period, pluralism(self.keywords), ', '.join(self.keywords))


class StaleUnstableReport(addons.StableCheckAddon):
    """Ebuilds that have sat unstable with no changes for over a month.

    By default, only triggered for arches with stable profiles. To check
    additional arches outside the stable set specify them manually using the
    -a/--arches option.

    Note that packages with no stable keywords won't trigger this at all.
    Instead they'll be caught by the UnstableOnly check.
    """
    feed_type = base.package_feed
    required_addons = (addons.ArchesAddon,)
    known_results = (StaleUnstable,)

    def __init__(self, options, arches, staleness=int(day*30)):
        super(StaleUnstableReport, self).__init__(options, arches)
        self.staleness = staleness
        self.start_time = None
        self.arches = frozenset(x.lstrip("~") for x in options.arches)

    def start(self):
        self.start_time = time.time()

    def feed(self, pkgset, reporter):
        pkg_slotted = defaultdict(list)
        for pkg in pkgset:
            pkg_slotted[pkg.slot].append(pkg)

        pkg_keywords = set(chain.from_iterable(pkg.keywords for pkg in pkgset))
        stale_pkgs = defaultdict(list)
        for slot, pkgs in sorted(pkg_slotted.items()):
            stable_keywords = pkg_keywords.intersection(self.arches)
            if stable_keywords:
                target_keywords = set('~' + x for x in stable_keywords)
                for pkg in pkgs:
                    unchanged_time = self.start_time - pkg._mtime_
                    if unchanged_time < self.staleness:
                        continue
                    unstable = [arch for arch in pkg.keywords if arch in target_keywords]
                    if unstable:
                        stale_pkgs[slot].append((pkg, unstable, int(unchanged_time/day)))

        for slot, pkgs in sorted(stale_pkgs.items()):
            if self.options.verbose:
                # output all stale pkgs in verbose mode
                for pkg_info in pkgs:
                    pkg, unstable, period = pkg_info
                    reporter.add_report(StaleUnstable(pkg, unstable, period))
            else:
                # only report the most recent stale pkg for each slot
                pkg, unstable, period = pkgs[-1]
                reporter.add_report(StaleUnstable(pkg, unstable, period))
