# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: GPL2

import time
from pkgcore_checks.base import (template, versioned_feed, Result,
    arches_options)

day = 24*3600
        

class StaleUnstableReport(template):
    """Ebuilds that have sat unstable for over a month"""

    feed_type = versioned_feed
    requires = arches_options
    
    def __init__(self, options, staleness=long(day*30)):
        template.__init__(self, options)
        self.arches = options.arches
        self.staleness = staleness
        self.start_time = None

    def start(self, repo):
        self.start_time = time.time()

    def feed(self, pkg, reporter):
        unchanged_time = self.start_time - pkg._mtime_
        if unchanged_time < self.staleness:
            return
        unstable = [x for x in pkg.keywords if x.startswith("~")]
        if not unstable:
            return
        reporter.add_report(StaleUnstableKeyword(pkg, int(unchanged_time/day)))


class StaleUnstableKeyword(Result):
    """
    packages that have unstable keywords that have been unstable for over a
    month
    """
    
    __slots__ = ("category", "package", "version", "keywords", "period")
    
    def __init__(self, pkg, period):
        Result.__init__(self)
        self._store_cpv(pkg)
        self.keywords = tuple(x for x in pkg.keywords if x.startswith("~"))
        self.period = period
    
    def to_str(self):
        return "%s/%s-%s: no change in %i days, keywords [ %s ]" % \
            (self.category, self.package, self.version, self.period, 
                ", ".join(self.keywords))

    def to_xml(self):
        return \
"""<check name="%s">
    <category>%s</category>
    <package>%s</package>
    <version>%s</version>
    <arch>%s</arch>
    <msg>left unstable for %i days</msg>
</check>""" % (self.__class__.__name__, self.category, self.package,
    self.version, "</arch>\n\t<arch>".join(x.lstrip("~") 
        for x in self.keywords), self.period)
