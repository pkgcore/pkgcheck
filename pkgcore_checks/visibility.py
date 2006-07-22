# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: GPL2

import os
from pkgcore.util.compatibility import any
from pkgcore.util.demandload import demandload
from pkgcore_checks import base, util, arches
from pkgcore.util.iterables import caching_iter, expandable_chain
from pkgcore.util.lists import stable_unique, iflatten_instance
from pkgcore.util.containers import ProtectedSet
from pkgcore.restrictions import packages, values
from pkgcore.package.atom import atom
demandload(globals(), "pkgcore.util.containers:InvertedContains")
demandload(globals(), "pkgcore.util.xml:escape")


class VisibilityReport(base.template):

	"""Visibility dependency scans.
	Check that at least one solution is possible for a pkg, checking all profiles (defined by arch.list) visibility modifiers per stable/unstable keyword
	"""

	feed_type = base.package_feed
	requires_profiles = True
	uses_caches = True

	vcs_eclasses = ("subversion", "git", "cvs", "darcs")

	def __init__(self, arches=arches.default_arches):
		self.arches = frozenset(x.lstrip("~") for x in arches)
		self.repo = self.profile_filters = None
		self.keywords_filter = None
	
	def start(self, repo, global_insoluable, keywords_filter, profile_filters):
		self.repo = repo
		self.global_insoluable = global_insoluable
		self.keywords_filter = keywords_filter
		self.profile_filters = profile_filters

	def feed(self, pkgset, reporter, feeder):
		# query_cache gets caching_iter partial repo searches shoved into it- reason is simple,
		# it's likely that versions of this pkg probably use similar deps- so we're forcing those
		# packages that were accessed for atom matching to remain in memory.
		# end result is less going to disk
		for pkg in pkgset:
			if any(True for eclass in self.vcs_eclasses if eclass in pkg.data["_eclasses_"]):
				# vcs ebuild that better not be visible
				self.check_visibility_vcs(pkg, reporter)
			self.check_pkg(pkg, feeder, reporter)

	def check_visibility_vcs(self, pkg, reporter):
		for key, profile_dict in self.profile_filters.iteritems():
			if not key.startswith("~"):
				continue
			for profile_name, vals in profile_dict.iteritems():
				if vals[3].match(pkg):
					reporter.add_report(VisibleVcsPkg(pkg, key, profile_name))
	

	def check_pkg(self, pkg, feeder, reporter):
		query_cache = feeder.query_cache
		nonexistant = set()
		for node in iflatten_instance(pkg.depends, atom):
			h = hash(node)
			if h not in query_cache:
				if h in self.global_insoluable:
					nonexistant.add(node)
					# insert an empty tuple, so that tight loops further on don't have to
					# use the slower get method
					query_cache[h] = ()
				else:
					matches = caching_iter(self.repo.itermatch(node))
					if matches:
						query_cache[h] = matches
					elif not node.blocks and not node.category == "virtual":
						nonexistant.add(node)
						query_cache[h] = ()
						self.global_insoluable.add(h)

		if nonexistant:
			reporter.add_report(NonExistantDeps(pkg, "depends", nonexistant))
			nonexistant.clear()

		# force it to be stable, then unstable ordering for an unstable optimization below
		for node in iflatten_instance(pkg.rdepends, atom):
			h = hash(node)
			if h not in query_cache:
				if h in self.global_insoluable:
					nonexistant.add(node)
					query_cache[h] = ()
				else:
					matches = caching_iter(self.repo.itermatch(node))
					if matches:
						query_cache[h] = matches
					elif not node.blocks and not node.category == "virtual":
						nonexistant.add(node)
						query_cache[h] = ()
						self.global_insoluable.add(h)

		if nonexistant:
			reporter.add_report(NonExistantDeps(pkg, "rdepends", nonexistant))
		del nonexistant

		for attr, depset in (("depends", pkg.depends), ("rdepends/pdepends", pkg.rdepends)):
			for edepset, profiles in feeder.collapse_evaluate_depset(pkg, attr, depset):
				self.process_depset(pkg, attr, edepset, profiles, query_cache, reporter)

	def process_depset(self, pkg, attr, depset, profiles, query_cache, reporter):
		csolutions = depset.cnf_solutions()
		failures = set()
		for key, profile_name, data in profiles:
			failures.clear()
			virtuals, flags, non_tristate, vfilter, cache, insoluable = data
			masked_status = not vfilter.match(pkg)
			for required in csolutions:
				if any(True for a in required if a.blocks):
					continue
				elif any(True for a in required if hash(a) in cache):
					continue
				for a in required:
					h = hash(a)
					if h in insoluable:
						pass
					elif virtuals.match(a):
						cache.add(h)
						break
					elif a.category == "virtual" and h not in query_cache:
						insoluable.add(h)
					else:
						if any(True for pkg in query_cache[h] if vfilter.match(pkg)):
							cache.add(h)
							break
						else:
							insoluable.add(h)
				else:
					# no matches.  not great, should collect them all
					failures.update(required)
					break
			else:
				# all requireds where satisfied.
				continue
			reporter.add_report(NonsolvableDeps(pkg, attr, key, profile_name, list(failures), masked=masked_status))

	def finish(self, *a):
		self.repo = self.profile_filters = self.keywords_filter = None


class VisibleVcsPkg(base.Result):
	"""pkg is vcs based, but visible"""
	__slots__ = ("category", "package", "version", "profile", "arch")

	def __init__(self, pkg, arch, profile):
		self.category, self.package, self.version = pkg.category, pkg.package, pkg.fullver
		self.arch = arch.lstrip("~")
		self.profile = profile
	
	def to_str(self):
		return "%s/%s-%s: vcs ebuild visible for arch %s, profile %s" % \
			(self.category, self.package, self.version, self.arch, self.profile)
	
	def to_xml(self):
		return \
"""<check name="%s">
	<category>%s</category>
	<package>%s</package>
	<version>%s</version>
	<arch>%s</arch>
	<profile>%s</profile>
	<msg>vcs based ebuild user accessible</msg>
</check>""" % (self.__class__.__name__, self.category, self.package, self.version,
	self.arch, self.profile)


class NonExistantDeps(base.Result):
	"""No matches exist for a depset element"""
	__slots__ = ("category", "package", "version", "attr", "atoms")
	
	def __init__(self, pkg, attr, nonexistant_atoms):
		self.category = pkg.category
		self.package = pkg.package
		self.version = pkg.fullver
		self.attr = attr
		self.atoms = tuple(str(x) for x in nonexistant_atoms)
		
	def to_str(self):
		return "%s/%s-%s: attr(%s): nonexistant atoms [ %s ]" % \
			(self.category, self.package, self.version, self.attr, ", ".join(self.atoms))

	def to_xml(self):
		return \
"""<check name="%s">
	<category>%s</category>
	<package>%s</package>
	<version>%s</version>
	<msg>%s: nonexistant atoms [ %s ]</msg>
</check>""" % (self.__class__.__name__, self.category, self.package, self.version,
self.attr, escape(", ".join(self.atoms)))


class NonsolvableDeps(base.Result):
	"""No potential solution for a depset attribute"""
	__slots__ = ("category", "package", "version", "attr", "profile", "keyword", 
		"potentials", "masked")
	
	def __init__(self, pkg, attr, keyword, profile, horked, masked=False):
		self.category = pkg.category
		self.package = pkg.package
		self.version = pkg.fullver
		self.attr = attr
		self.profile = profile
		self.keyword = keyword
		self.potentials = tuple(str(x) for x in stable_unique(horked))
		self.masked = masked
		
	def to_str(self):
		s=' '
		if self.keyword.startswith("~"):
			s=''
		if self.masked:
			s = "masked "+s
		return "%s/%s-%s: %s %s%s: unsolvable %s, solutions: [ %s ]" % \
			(self.category, self.package, self.version, self.attr, s, self.keyword, self.profile,
			", ".join(self.potentials))

	def to_xml(self):
		s = ''
		if self.masked:
			s = "masked, "
		return \
"""<check name="%s">
	<category>%s</category>
	<package>%s</package>
	<version>%s</version>
	<profile>%s</profile>
	<keyword>%s</keyword>
	<msg>%snot solvable for %s- potential solutions, %s</msg>
</check>""" % (self.__class__.__name__, self.category, self.package, self.version,
self.profile, self.keyword, s, self.attr, escape(", ".join(self.potentials)))
