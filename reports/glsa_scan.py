from reports.base import package_feed, template
from pkgcore.pkgsets.glsa import GlsaDirSet
from pkgcore.restrictions.util import collect_package_restrictions
from pkgcore.restrictions import packages
from pkgcore.fs.util import ensure_dirs
import logging, os

class TreeVulnerabilitiesReport(template):
	feed_type = package_feed
	
	def __init__(self, location):
		self.location = location
		self.reportf = None
		self.vulnerabilities = []
	
	def start(self, repo):
		if not ensure_dirs(self.location, mode=0755):
			raise Exception("failed creating reports directory %s" % self.location)
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
				self.reportf.write("%s\naffected:   %s\navailable:  %s\n\n" % \
					(vuln, ", ".join(str(x) for x in affected), ", ".join(str(x) for x in pkgset)))

	def finish(self):
		self.reportf.close()
		self.reportf = None
		self.vulns = None
