# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: BSD/GPL2

import time

from pkgcheck.addons import ArchesAddon, StableCheckAddon
from pkgcheck.base import versioned_feed, Result

day = 24*3600


class StaleUnstableKeyword(Result):
    """
    packages that have unstable keywords that have been unstable for over a
    month
    """

    __slots__ = ("category", "package", "version", "keywords", "period")

    threshold = versioned_feed

    def __init__(self, pkg, keywords, period):
        Result.__init__(self)
        self._store_cpv(pkg)
        self.keywords = tuple(sorted(keywords))
        self.period = period

    @property
    def short_desc(self):
        return "no change in %i days for unstable keyword%s: [ %s ]" % (
            self.period, 's'[len(self.keywords) == 1:], ', '.join(self.keywords))


class StaleUnstableReport(StableCheckAddon):
    """Ebuilds that have sat unstable for over a month"""

    feed_type = versioned_feed
    required_addons = (ArchesAddon,)
    known_results = (StaleUnstableKeyword,)

    def __init__(self, options, arches, staleness=long(day*30)):
        super(StaleUnstableReport, self).__init__(options)
        self.staleness = staleness
        self.start_time = None
        self.arches = frozenset("~%s" % x.lstrip("~") for x in self.arches)

    def start(self):
        self.start_time = time.time()

    def feed(self, pkg, reporter):
        unchanged_time = self.start_time - pkg._mtime_
        if unchanged_time < self.staleness:
            return
        unstable = [arch for arch in pkg.keywords if arch in self.arches]
        if not unstable:
            return
        reporter.add_report(
            StaleUnstableKeyword(pkg, unstable, int(unchanged_time/day)))
