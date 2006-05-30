# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: GPL2

import time, os
from reports.base import template, versioned_feed, Result
from reports.arches import default_arches

day = 24*3600


class StaleUnstableKeyword(Result):
	description = "packages that have unstable keywords that have been unstable for over a month"
	
	__slots__ = ("category", "package", "version", "keywords", "period")
	
	def __init__(self, pkg, period):
		self.category = pkg.category
		self.package = pkg.package
		self.version = pkg.fullver
		self.keywords = tuple(x for x in pkg.keywords if x.startswith("~"))
		self.period = period
	
	def to_str(self):
		return "%s/%s-%s: no change in %i days, keywords [ %s ]" % \
			(self.category, self.package, self.version, self.period, ", ".join(self.keywords))

	def to_xml(self):
		return \
"""<check name="%s">
	<category>%s</category>
	<package>%s</package>
	<version>%s</version>
	<arch>%s</arch>
	<msg>left unstable for %i days</msg>
</check>""" % (self.__class__.__name__, self.category, self.package, self.version,
"</arch>\n\t<arch>".join(x.lstrip("~") for x in self.keywords), self.period)
		

class StaleUnstableReport(template):
	feed_type = versioned_feed
	
	def __init__(self, location, arches=default_arches, staleness=long(day*30)):
		self.arches = default_arches
		self.staleness = staleness
	
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
