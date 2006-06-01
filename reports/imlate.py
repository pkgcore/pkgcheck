# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: GPL2

from pkgcore.restrictions import packages, values
from reports.base import template, package_feed, Result

from reports.arches import default_arches

class LaggingStableInfo(Result):
	description = "Arch that is behind another from a stabling standpoint"
	__slots__ = ("category", "package", "version", "keywords", "existing_keywords")
	
	def __init__(self, pkg, keywords):
		self.category = pkg.category
		self.package = pkg.package
		self.version = pkg.fullver
		self.keywords = keywords
		self.stable = tuple(str(x) for x in pkg.keywords if not x.startswith("~") and not x.startswith("-"))
	
	def to_str(self):
		return "%s/%s-%s: stabled [ %s ], potentials: [ %s ], " % \
			(self.category, self.package, self.version, 
			", ".join(self.stable), ", ".join(self.keywords))

	def to_xml(self):
		return \
"""<check name="%s">
	<category>%s</category>
	<package>%s</package>
	<version>%s</version>
	<keyword>%s</keyword>
	<msg>%s</msg>
</check>""" % (self.__class__.__name__, self.category, self.package, self.version, 
"</keyword>\n\t<keyword>".join(self.keyword), 
"potential for stabling, prexisting stable- %s" % ", ".join(self.stable))
		

class ImlateReport(template):
	feed_type = package_feed

	def __init__(self, location, arches=default_arches):
		arches = set(x.strip().lstrip("~") for x in arches)
		# stable, then unstable, then file
		self.any_stable = packages.PackageRestriction("keywords", 
			values.ContainmentMatch(*default_arches))

	def feed(self, pkgset, reporter):
		# stable, then unstable, then file
		try:
			max_stable = max(pkg for pkg in pkgset if self.any_stable.match(pkg))
		except ValueError:
			# none stable.
			return
		unstable_keys = tuple(str(x) for x in max_stable.keywords if x.startswith("~"))
		if unstable_keys:
			reporter.add_report(LaggingStableInfo(max_stable, unstable_keys))
