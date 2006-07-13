# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: GPL2

import time, os
from pkgcore_checks.base import template, package_feed, Result
from pkgcore_checks.arches import default_arches


class DroppedKeywordWarning(Result):
	description = "Arch keywords dropped during pkg version bumping"

	__slots__ = ("arch", "category", "package",)

	def __init__(self, arch, pkg):
		self.arch = arch
		self.category = pkg.category
		self.package = pkg.package
		self.version = pkg.fullver
	
	def to_str(self, **kwds):
		return "%s/%s-%s: dropped keyword %s" % (self.category, self.package, self.version,
			self.arch)

	def to_xml(self):
		return \
"""<check name="%s">
	<category>%s</category>
	<package>%s</package>
	<version>%s</version>
	<arch>%s</arch>
	<msg>keyword was dropped</msg>
</check>""" % (self.__class__.__name__, self.category, self.package, self.version, self.arch)


class DroppedKeywordsReport(template):
	"""scan pkgs for keyword dropping across versions"""

	feed_type = package_feed
	
	def __init__(self, arches=default_arches):
		self.arches = {}.fromkeys(default_arches)
	
	def feed(self, pkgset, reporter):
		if len(pkgset) == 1:
			return
		
		lastpkg = pkgset[-1]
		state = set(x.lstrip("~") for x in lastpkg.keywords)
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
					dropped.append((key, lastpkg))
					arches.discard(key)
			state = oldstate
			lastpkg = pkg
		for key, pkg in dropped:
			reporter.add_report(DroppedKeywordWarning(key, pkg))
