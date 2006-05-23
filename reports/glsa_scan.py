# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: GPL2

from reports.base import package_feed, template
from pkgcore.pkgsets.glsa import GlsaDirSet
from pkgcore.restrictions.util import collect_package_restrictions
from pkgcore.restrictions import packages, values
from pkgcore.fs.util import ensure_dirs
import logging, os

from reports.arches import default_arches

class TreeVulnerabilitiesReport(template):
	feed_type = package_feed
	
	def __init__(self, location, arches_we_care_about=default_arches):
		self.location = location
		self.per_arch_location = os.path.join(location, "arch-vulnerabilities")
		self.reportf = None
		self.arch_limiters = frozenset(default_arches)
		self.vulnerabilities = []
		self.arch_reports = dict((x, [packages.PackageRestriction("keywords", 
			values.ContainmentMatch(x.lstrip("~"), "~%s" % x.lstrip("~"))), None])
			for x in arches_we_care_about)
	
	def start(self, repo):
		if not ensure_dirs(self.location, mode=0755):
			raise Exception("failed creating reports directory: %s" % self.location)
		if not ensure_dirs(self.per_arch_location, mode=0755):
			raise Exception("failed creating per arch reports dir: %s" % self.per_arch)
		self.vulns = {}
		# this is a bit brittle
		for r in GlsaDirSet(repo):
			if len(r) > 2:
				self.vulns.setdefault(r[0].key, []).append(packages.AndRestriction(*r[1:]))
			else:
				self.vulns.setdefault(r[0].key, []).append(r[1])
			
		self.reportf = open(os.path.join(self.location, "tree-vulnerabilities"), "w", 8096)
		
	def feed(self, pkgset):
		for vuln in self.vulns.get(pkgset[0].key, []):
			affected = filter(vuln.match, pkgset)
			if affected:
				self.write_entry(self.reportf, vuln, affected, pkgset)
				for arch, v in self.arch_reports.iteritems():
					arch_affected = filter(v[0].match, affected)
					if arch_affected:
						if v[1] is None:
							v[1] = open(os.path.join(self.per_arch_location, arch), "w", 8096)
						self.write_entry(v[1], vuln, arch_affected, filter(v[0].match, pkgset))

	@staticmethod
	def write_entry(fd, vuln, affected, available):
		fd.write("%s\naffected:   %s\navailable:  %s\n\n" % \
			(vuln, ", ".join(str(x) for x in affected), ", ".join(str(x) for x in available)))

	def finish(self):
		self.reportf.close()
		self.reportf = None
		self.vulns = None
		for v in self.arch_reports.itervalues():
			if v[1] is not None:
				v[1].close()
				v[1] = None
