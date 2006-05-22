# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: GPL2

from pkgcore.restrictions import packages, values
from reports.base import template, package_feed
from pkgcore.fs.util import ensure_dirs
import os, logging

from reports.arches import default_arches


class ImlateReport(template):
	feed_type = package_feed

	def __init__(self, location, arches=default_arches):
		self.location = os.path.join(location, "imlate")
		arches = set(x.strip().lstrip("~") for x in arches)
		# stable, then unstable, then file
		self.any_stable = packages.PackageRestriction("keywords", 
			values.ContainmentMatch(*default_arches))

		self.arch_restricts = {}
		for x in arches:
			self.arch_restricts[x] = ["~" + x, "-" + x, None]

	def start(self, repo):
		if not ensure_dirs(self.location, mode=0755):
			raise Exception("unable to create report dir %s" % self.location)
		for k, v in self.arch_restricts.iteritems():
			v[2] = open(os.path.join(self.location, k), "w", 8096)
	
	def finish(self):
		for k, v in self.arch_restricts.iteritems():
			try:
				v[2].close()
			except (OSError, IOError, AttributeError), e:
				logging.error("arch file %s exception %s" % (k, e))
			v[2] = None
	
	def feed(self, pkgset):
		# stable, then unstable, then file
		try:
			max_stable = max(pkg for pkg in pkgset if self.any_stable.match(pkg))
		except ValueError:
			# none stable.
			return
		keys = frozenset(max_stable.keywords)
		for k, v in self.arch_restricts.iteritems():
			if k in max_stable.keywords:
				continue
			# if ~k is there, we flag it
			if v[0] in keys and v[1] not in keys:
				self.write_entry(v[-1], max_stable)
				
	@staticmethod
	def write_entry(fileobj, pkg):
		fileobj.write("%s: keywords: [ %s ]\n" % (str(pkg), 
			", ".join(str(x) for x in pkg.keywords)))
