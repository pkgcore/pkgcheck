# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: GPL2

import os
from pkgcore.util.compatibility import any
from pkgcore.util.demandload import demandload
from reports import base, util, arches
from pkgcore.fs.util import ensure_dirs
from pkgcore.util.iterables import caching_iter
from pkgcore.util.lists import stable_unique
demandload(globals(), "pkgcore.restrictions:packages,values")
demandload(globals(), "pkgcore.util.containers:InvertedContains")


class BrokenDepsReport(base.template):

	feed_type = base.package_feed

	def __init__(self, location, arches=arches.default_arches):
		self.location = os.path.join(location, "broken-deps")
		self.arches = frozenset(x.lstrip("~") for x in arches)
		self.repo = self.reportf = self.profile_filters = None
		self.keywords_filter = None
	
	def start(self, repo):
		if not ensure_dirs(os.path.dirname(self.location), mode=0775):
			raise Exception("failed creating required dir %s" % os.path.dirname(self.location))
		self.reportf = open(self.location, "w", 8096)
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
				virtuals = profile.virtuals
				# force all use masks to negated, and all other arches but this
				use_flags = InvertedContains(profile.use_mask + tuple(official_arches.difference([stable_key])))
			
				# ensure keywords is last, else it triggers a metadata pull
				# filter is thus- not masked, and keywords match

				# virtual repo, flags, visibility filter, known_good, known_bad
				profile_filters[stable_key][profile_name] = \
					[virtuals, use_flags, packages.AndRestriction(mask, stable_r), set(), set()]
				profile_filters[unstable_key][profile_name] = \
					[virtuals, use_flags, packages.AndRestriction(mask, unstable_r), set(), set()]

			self.keywords_filter[stable_key] = stable_r
			self.keywords_filter[unstable_key] = unstable_r

		self.profile_filters = profile_filters
		self.repo = repo

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

	def feed(self, pkgset):
		query_cache = {}
		# query_cache gets caching_iter partial repo searches shoved into it- reason is simple,
		# it's likely that versions of this pkg probably use similar deps- so we're forcing those
		# packages that were accessed for atom matching to remain in memory.
		# end result is less going to disk
		for pkg in pkgset:			
			self.check_pkg(pkg, query_cache)
		
	def check_pkg(self, pkg, query_cache):
		failures = {}
		for key, key_r in self.keywords_filter.iteritems():
			if not key_r.match(pkg):
				continue
			for profile, val in self.profile_filters[key].iteritems():
				virtuals, flags, vfilter, cache, insoluable = val
				bad = self.process_depset(pkg.depends.evaluate_depset(flags), 
					virtuals, vfilter, cache, insoluable, query_cache)
				if bad:
					failures.setdefault(key, {})[profile] = ("depends", bad)
				r = pkg.rdepends.evaluate_depset(flags)
				bad = self.process_depset(r,
					virtuals, vfilter, cache, insoluable, query_cache)
				if bad:
					failures.setdefault(key, {})[profile] = ("rdepends", bad)

		if failures:
			self.reportf.write("%s:\n" % pkg)
			for key, profile_dict in failures.iteritems():
				for profile_name, val in profile_dict.iteritems():
					self.reportf.writelines("  %s, %s: %s [ %s ]\n" % (key, profile_name, val[0],
						", ".join(str(x) for x in stable_unique(val[1]))))
			self.reportf.write("\n")
	
					
	def finish(self):
		self.reportf.close()
		self.repo = self.profile_filters = self.keywords_filter = None
