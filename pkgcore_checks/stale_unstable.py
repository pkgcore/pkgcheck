# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: GPL2

import time
from pkgcore_checks.base import Template, versioned_feed, Result
from pkgcore_checks import addons

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
        return "no change in %i days for unstable keywords [ %s ]" % (
            self.period, ', '.join(self.keywords))
    

class StaleUnstableReport(Template):
    """Ebuilds that have sat unstable for over a month"""

    feed_type = versioned_feed
    required_addons = (addons.ArchesAddon,)
    known_results = (StaleUnstableKeyword,)

    def __init__(self, options, arches, staleness=long(day*30)):
        Template.__init__(self, options)
        self.staleness = staleness
        self.start_time = None
        self.targets = frozenset("~%s" % x.lstrip("~") for x in options.arches)

    def start(self):
        self.start_time = time.time()

    def feed(self, pkg, reporter):
        unchanged_time = self.start_time - pkg._mtime_
        if unchanged_time < self.staleness:
            return
        unstable = [x for x in pkg.keywords if x in self.targets]
        if not unstable:
            return
        reporter.add_report(
            StaleUnstableKeyword(pkg, unstable, int(unchanged_time/day)))
