from pkgcore.restrictions import packages, values
from reports.base import template, package_feed
from pkgcore.fs.util import ensure_dirs
import os, logging

default_arches = ("x86", "x86-fbsd", "amd64", "ppc", "ppc-macos", "ppc64", 
	"sparc", "mips", "arm", "hppa", "m68k", "ia64", "s390", "sh")

class UnstableOnlyReport(template):
	feed_type = package_feed

	def __init__(self, location, arches=default_arches):
		self.location = os.path.join(location, "unstable_only")
		arches = set(x.strip().lstrip("~") for x in arches)
		# stable, then unstable, then file
		self.arch_restricts = {}
		for x in arches:
			self.arch_restricts[x] = [packages.PackageRestriction("keywords", values.ContainmentMatch(x)),
				packages.PackageRestriction("keywords", values.ContainmentMatch("~%s" % x)), None]

	def start(self, repo):
		if not ensure_dirs(self.location, mode=0755):
			raise Exception("failed to create reports dirs %s" % self.location)
		for k,v in self.arch_restricts.iteritems():
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
		for k, v in self.arch_restricts.iteritems():
			stable = unstable = None
			for x in pkgset:
				if v[0].match(x):
					stable = x
					break
			if stable is not None:
				continue
			unstable = [x for x in pkgset if v[1].match]
			if unstable:
				self.write_entry(v[2], unstable, "%s/%s" % (unstable[0].category, unstable[0].package))
				
	@staticmethod
	def write_entry(fileobj, unstable, catpkg):
		fileobj.write("%s: all unstable: [ %s ]\n" % (catpkg, ", ".join(str(x) for x in unstable)))
