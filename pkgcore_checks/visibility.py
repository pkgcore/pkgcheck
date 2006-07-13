# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: GPL2

import os
from pkgcore.util.compatibility import any
from pkgcore.util.demandload import demandload
from pkgcore_checks import base, util, arches
from pkgcore.util.iterables import caching_iter, expandable_chain
from pkgcore.util.lists import stable_unique, iter_flatten
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

	vcs_eclasses = ("subversion", "git", "cvs", "darcs")

	def __init__(self, arches=arches.default_arches):
		self.arches = frozenset(x.lstrip("~") for x in arches)
		self.repo = self.profile_filters = None
		self.keywords_filter = None
	
	def start(self, repo):
		arches_dict = util.get_profiles_desc(repo)
		official_arches = util.get_repo_known_arches(repo)
		profile_filters = {}
		self.keywords_filter = {}
		self.global_insoluable = set()
		for k in arches_dict.keys():
			if k.lstrip("~") not in self.arches:
				del arches_dict[k]
				continue
			stable_key = k.lstrip("~")
			unstable_key = "~"+ stable_key
			stable_r = packages.PackageRestriction("keywords", 
				values.ContainmentMatch(stable_key))
			unstable_r = packages.PackageRestriction("keywords", 
				values.ContainmentMatch(stable_key, unstable_key))
			
			profile_filters.update({stable_key:{}, unstable_key:{}})
			for profile_name in arches_dict[k]:
				profile = util.get_profile(repo, profile_name)
				mask = util.get_profile_mask(profile)
				virtuals = profile.virtuals(repo)
				# force all use masks to negated, and all other arches but this
#				use_flags = InvertedContains(profile.use_mask + tuple(official_arches.difference([stable_key])))
				non_tristate = tuple(official_arches) + tuple(profile.use_mask)
				use_flags = [stable_key]
				# used to interlink stable/unstable lookups so that if unstable says it's not visible, stable doesn't try
				# if stable says something is visible, unstable doesn't try.
				stable_cache = set()
				unstable_insoluable = ProtectedSet(self.global_insoluable)

				# ensure keywords is last, else it triggers a metadata pull
				# filter is thus- not masked, and keywords match

				# virtual repo, flags, visibility filter, known_good, known_bad
				profile_filters[stable_key][profile_name] = \
					[virtuals, use_flags, non_tristate, packages.AndRestriction(mask, stable_r), 
						stable_cache, ProtectedSet(unstable_insoluable)]
				profile_filters[unstable_key][profile_name] = \
					[virtuals, use_flags, non_tristate, packages.AndRestriction(mask, unstable_r), 
						ProtectedSet(stable_cache), unstable_insoluable]

			self.keywords_filter[stable_key] = stable_r
			self.keywords_filter[unstable_key] = packages.PackageRestriction("keywords", 
				values.ContainmentMatch(unstable_key))

		self.profile_filters = profile_filters
		self.repo = repo

	def feed(self, pkgset, reporter):
		query_cache = {}
		# query_cache gets caching_iter partial repo searches shoved into it- reason is simple,
		# it's likely that versions of this pkg probably use similar deps- so we're forcing those
		# packages that were accessed for atom matching to remain in memory.
		# end result is less going to disk
		for pkg in pkgset:
			if any(True for eclass in self.vcs_eclasses if eclass in pkg.data["_eclasses_"]):
				# vcs ebuild that better not be visible
				self.check_visibility_vcs(pkg, reporter)
			self.check_pkg(pkg, query_cache, reporter)

	def check_visibility_vcs(self, pkg, reporter):
		for key, profile_dict in self.profile_filters.iteritems():
			if not key.startswith("~"):
				continue
			for profile_name, vals in profile_dict.iteritems():
				if vals[3].match(pkg):
					reporter.add_report(VisibleVcsPkg(pkg, key, profile_name))
	

	def check_pkg(self, pkg, query_cache, reporter):
		nonexistant = set()
		for node in iter_flatten(pkg.depends, atom):
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
		for node in iter_flatten(pkg.rdepends, atom):
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
		
		for key in sorted(self.keywords_filter):
			if not self.keywords_filter[key].match(pkg):
				continue
			for profile, val in self.profile_filters[key].iteritems():
				virtuals, flags, non_tristate, vfilter, cache, insoluable = val
				masked_status = not vfilter.match(pkg)
				r = pkg.depends.evaluate_depset(flags, tristate_filter=non_tristate)
				bad = self.process_depset(r, 
					virtuals, vfilter, cache, insoluable, query_cache)
				if bad:
					reporter.add_report(NonsolvableDeps(pkg, "depends", key, profile, bad, masked=masked_status))
				r = pkg.rdepends.evaluate_depset(flags, tristate_filter=non_tristate)
				bad = self.process_depset(r,
					virtuals, vfilter, cache, insoluable, query_cache)
				if bad:
					reporter.add_report(NonsolvableDeps(pkg, "rdepends/pdepends", key, profile, bad, masked=masked_status))

	def process_depset(self, depset, virtuals, vfilter, cache, insoluable, query_cache):
		failures = set()
		for required in depset.cnf_solutions():
			if any(True for a in required if a.blocks):
				continue
			if any(True for a in required if hash(a) in cache):
				continue
			for a in required:
				h = hash(a)
				if h in insoluable:
					continue
				if virtuals.match(a):
					cache.add(h)
					break
				elif a.category == "virtual" and h not in query_cache:
					insoluable.add(h)
					continue
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
			return ()
		return list(failures)

	def finish(self, *a):
		self.repo = self.profile_filters = self.keywords_filter = None


class VisibleVcsPkg(base.Result):
	description = "pkg is vcs based, but visible"
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
	description = "No matches exist for a depset element"
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
	description = "No potential solution for a depset attribute"
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
