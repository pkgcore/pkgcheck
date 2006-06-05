# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: GPL2

import os
from pkgcore.util.compatibility import any
from pkgcore.util.demandload import demandload
from pkgcore_checks import base, util, arches
from pkgcore.util.iterables import caching_iter
from pkgcore.util.lists import stable_unique
from pkgcore.util.containers import ProtectedSet
demandload(globals(), "pkgcore.restrictions:packages,values")
demandload(globals(), "pkgcore.util.containers:InvertedContains")
demandload(globals(), "pkgcore.util.xml:escape")


class VisibilityReport(base.template):

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
				use_flags = InvertedContains(profile.use_mask + tuple(official_arches.difference([stable_key])))

				# used to interlink stable/unstable lookups so that if unstable says it's not visible, stable doesn't try
				# if stable says something is visible, unstable doesn't try.
				stable_cache = set()
				unstable_insoluable = set()

				# ensure keywords is last, else it triggers a metadata pull
				# filter is thus- not masked, and keywords match

				# virtual repo, flags, visibility filter, known_good, known_bad
				profile_filters[stable_key][profile_name] = \
					[virtuals, use_flags, packages.AndRestriction(mask, stable_r), stable_cache, ProtectedSet(unstable_insoluable)]
				profile_filters[unstable_key][profile_name] = \
					[virtuals, use_flags, packages.AndRestriction(mask, unstable_r), ProtectedSet(stable_cache), unstable_insoluable]

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
				if vals[2].match(pkg):
					reporter.add_report(VisibleVcsPkg(pkg, key, profile_name))
	

	def check_pkg(self, pkg, query_cache, reporter):
		# force it to be stable, then unstable ordering for an unstable optimization below
		for key in sorted(self.keywords_filter):
			if not self.keywords_filter[key].match(pkg):
				continue
			for profile, val in self.profile_filters[key].iteritems():
				virtuals, flags, vfilter, cache, insoluable = val
				bad = self.process_depset(pkg.depends.evaluate_depset(flags), 
					virtuals, vfilter, cache, insoluable, query_cache)
				if bad:
					reporter.add_report(NonsolvableDeps(pkg, "depends", key, profile, bad))
				r = pkg.rdepends.evaluate_depset(flags)
				bad = self.process_depset(r,
					virtuals, vfilter, cache, insoluable, query_cache)
				if bad:
					reporter.add_report(NonsolvableDeps(pkg, "rdepends/pdepends", key, profile, bad))

	def process_depset(self, depset, virtuals, vfilter, cache, insoluable, query_cache):
		failures = set()
		for potential in depset.solutions():
			for atom in potential:
				if atom.blocks:
					continue
				h = hash(atom)
				if h in cache:
					continue
				elif h in insoluable:
					# non solution, we know this won't work.
					break
				if virtuals.match(atom):
					cache.add(h)
				else:
					add_it = h not in query_cache
					if add_it:
						matches = caching_iter(self.repo.itermatch(atom))
					else:
						matches = query_cache[h]
					if any(vfilter.match(pkg) for pkg in matches):
						cache.add(h)
						if add_it:
							query_cache[h] = matches
					else:
						# no matches.
						insoluable.add(h)
						failures.add(atom)
						break
			else:
				# all nodes were visible.
				break
		else:
			# no matches for any of the potentials.
			return list(failures)
		return ()
					
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

class NonsolvableDeps(base.Result):
	description = "No potential solution for a depset attribute"
	__slots__ = ("category", "package", "version", "attr", "profile", "keyword", "nonvisible")
	
	def __init__(self, pkg, attr, keyword, profile, horked):
		self.category = pkg.category
		self.package = pkg.package
		self.version = pkg.fullver
		self.attr = attr
		self.profile = profile
		self.keyword = keyword
		self.nonvisible = tuple(str(x) for x in stable_unique(horked))
		
	def to_str(self):
		s=' '
		if self.keyword.startswith("~"):
			s=''
		return "%s/%s-%s: %s%s:%s: unsolvable %s, solutions: [ %s ]" % \
			(self.category, self.package, self.version, s, self.attr, self.keyword, self.profile,
			", ".join(self.nonvisible))

	def to_xml(self):
		return \
"""<check name="%s">
	<category>%s</category>
	<package>%s</package>
	<version>%s</version>
	<profile>%s</profile>
	<keyword>%s</keyword>
	<msg>not solvable for %s- potential solutions, %s</msg>
</check>""" % (self.__class__.__name__, self.category, self.package, self.version,
self.profile, self.keyword, self.attr, escape(", ".join(self.nonvisible)))
