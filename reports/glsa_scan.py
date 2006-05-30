# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: GPL2

from reports.base import versioned_feed, template, Result
from pkgcore.pkgsets.glsa import GlsaDirSet
from pkgcore.restrictions.util import collect_package_restrictions
from pkgcore.restrictions import packages, values
from pkgcore.util.xml import escape


class VulnerablePackage(Result):

	description = "Packages marked as vulnerable by GLSAs"

	__slots__ = ("category", "package", "version", "arch", "glsa")

	def __init__(self, pkg, glsa, arch_override=None):
		self.category = pkg.category
		self.package = pkg.package
		self.version = pkg.fullver
		if arch_override is None:
			self.arch = tuple(set(x.lstrip("~") for x in pkg.keywords))
		else:
			self.arch = arch
		self.glsa = str(glsa)
	
	def to_str(self):
		return "%s/%s-%s: vulnerable via %s, affects %s" % (self.category, self.package, self.version, self.glsa, self.arch)

	def to_xml(self):
		return \
"""<check name="%s">
	<category>%s</category>
	<package>%s</package>
	<version>%s</version>
	<arch>%s</arch>
	<msg>vulnerable via %s</msg>
</check>""" % (self.__class__.__name__, self.category, self.package, self.version, 
"</arch>\n\t<arch>".join(self.arch), escape(self.glsa))


class TreeVulnerabilitiesReport(template):
	feed_type = versioned_feed
	
	def __init__(self, location):
		self.location = location
		self.reportf = None
	
	def start(self, repo):
		self.vulns = {}
		# this is a bit brittle
		for r in GlsaDirSet(repo):
			if len(r) > 2:
				self.vulns.setdefault(r[0].key, []).append(packages.AndRestriction(*r[1:]))
			else:
				self.vulns.setdefault(r[0].key, []).append(r[1])
			
	def feed(self, pkg, reporter):
		for vuln in self.vulns.get(pkg.key, []):
			if vuln.match(pkg):
				reporter.add_report(VulnerablePackage(pkg, vuln))
