# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: GPL2

import time, os
from reports.base import template, package_feed
from pkgcore.fs.util import ensure_dirs
from reports.arches import default_arches

class StaleUnstableReport(template):
	feed_type = package_feed
	
	def __init__(self, location, arches=default_arches):
		self.location = os.path.join(location, "dropped-keywords")
		self.arches = {}.fromkeys(default_arches)
	
	def start(self, repo):
		if not ensure_dirs(self.location, mode=0755):
			raise Exception("failed creating reports directory %s" % self.location)
		for k in self.arches:
			self.arches[k] = open(os.path.join(self.location, k), "w", 8096)
		
	def feed(self, pkgset):
		if len(pkgset) == 1:
			return
			
		state = set(x.lstrip("~") for x in pkgset[-1].keywords)
		arches = set(self.arches)
		dropped = []
		for pkg in reversed(pkgset[:-1]):
			oldstate = set(x.lstrip("~") for x in pkg.keywords)
			for key in oldstate.difference(state):
				if key.startswith("-"):
					continue
				elif "-%s" % key in state:
					continue
				elif key in arches:
					dropped.append((key, pkg))
					arches.discard(key)
			state = oldstate
		for key, pkg in dropped:
			self.arches[key].write("%s: dropped at %s\n" % (pkg.key, pkg))
			
			

	def finish(self):
		for k in self.arches:
			self.arches[k].close()
			self.arches[k] = None
