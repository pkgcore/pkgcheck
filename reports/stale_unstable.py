import time, os
from reports.base import template, versioned_feed
from pkgcore.fs.util import ensure_dirs
from reports.arches import default_arches

day = 24*3600

class StaleUnstableReport(template):
	feed_type = versioned_feed
	
	def __init__(self, location, arches=default_arches, staleness=long(day*30)):
		self.location = location
		self.arches = default_arches
		self.staleness = staleness
		self.reportf = None
	
	def start(self, repo):
		if not ensure_dirs(self.location, mode=0755):
			raise Exception("failed creating reports directory %s" % self.location)
		self.start_time = time.time()
		self.reportf = open(os.path.join(self.location, "stale-unstable"), "w", 8096)
		
	def feed(self, pkg):
		unchanged_time = self.start_time - pkg._mtime_
		if unchanged_time < self.staleness:
			return
		unstable = [x for x in pkg.keywords if x.startswith("~")]
		if not unstable:
			return
		self.reportf.write("pkg %s hasn't changed in %i days: unstable keywords [ %s ]\n" % \
			(pkg, unchanged_time/day, ", ".join(unstable)))

	def finish(self):
		self.reportf.close()
		self.reportf = None
