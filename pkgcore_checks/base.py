# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: GPL2

category_feed = "cat"
package_feed = "cat/pkg"
versioned_feed = "cat/pkg-ver"

__all__ = ("package_feed, versioned_feed", "category_feed", "Feeder")

from pkgcore.restrictions import packages
from pkgcore.restrictions.util import collect_package_restrictions
from pkgcore_checks import util, arches
from pkgcore.util.mappings import OrderedDict
from pkgcore.util.containers import ProtectedSet
from pkgcore.util.compatibility import any
from pkgcore.restrictions import values, packages
import logging, operator


class template(object):
	feed_type = None
	requires_profiles = False
	uses_caches = False

	def __init__(self):
		pass

	def start(self, repo):
		pass

	def finish(self, reporter):
		pass
	
	def process(self, chunk, reporter):
		raise NotImplementedError


class _WipeQueryCache(template):
	uses_caches = True
	feed_type = package_feed

	def feed(self, pkgs, reporter, feeder):
		feeder.query_cache.clear()


class Feeder(object):
	def __init__(self, repo, desired_arches=arches.default_arches):
		self.pkg_checks = []
		self.cat_checks = []
		self.cpv_checks = []
		self.first_run = True
		self.repo = repo
		self.desired_arches = desired_arches
		self.profiles = {}
		self.profiles_inited = False
		self.query_cache = {}

	def clear_caches(self):
		self.profiles = {}

	def init_arch_profiles(self):
		if self.profiles_inited:
			return
		self.arch_profiles = util.get_profiles_desc(self.repo)

		if self.desired_arches is None:
			self.desired_arches = util.get_repo_known_arches(self.repo)

		self.global_insoluable = set()
		profile_filters = {}
		self.keywords_filter = {}
		for k in self.desired_arches:
			if k.lstrip("~") not in self.desired_arches:
				continue
			stable_key = k.lstrip("~")
			unstable_key = "~"+ stable_key
			stable_r = packages.PackageRestriction("keywords", 
				values.ContainmentMatch(stable_key))
			unstable_r = packages.PackageRestriction("keywords", 
				values.ContainmentMatch(stable_key, unstable_key))
			
			profile_filters.update({stable_key:{}, unstable_key:{}})
			for profile_name in self.arch_profiles[k]:
				profile = util.get_profile(self.repo, profile_name)
				mask = util.get_profile_mask(profile)
				virtuals = profile.virtuals(self.repo)
				# force all use masks to negated, and all other arches but this
				non_tristate = frozenset(list(self.desired_arches) + list(profile.use_mask))
				use_flags = frozenset([stable_key])
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

		self.keywords_filter = OrderedDict((k, self.keywords_filter[k]) for k in sorted(self.keywords_filter))
		self.profile_filters = profile_filters
		self.profiles_inited = True

	def add_check(self, check):
		feed_type = getattr(check, "feed_type")
		if feed_type == category_feed:
			self.cat_checks.append(check)
		elif feed_type == package_feed:
			self.pkg_checks.append(check)
		elif feed_type == versioned_feed:
			self.cpv_checks.append(check)
		else:
			raise TypeError("check feed_type %s unknown for %s" % (feed_type, check))
	
	def _generic_fire(self, attr, check_type, checks, *args):
		if not checks:
			return
		actual = []
		for check in checks:
			if attr == "start" and getattr(check, "requires_profiles", False):
				a = args + (self.global_insoluable, self.keywords_filter, self.profile_filters)
			else:
				a = args
			try:
				getattr(check, attr)(*a)
				actual.append(check)
			except SystemExit:
				raise
			except Exception, e:
				logging.error("type %s, check %s failed to running %s: %s" % (check_type, check, attr, e))
				del e
		# rebuild the checks should any have failed
		for x in xrange(len(checks)):
			checks.pop()
		checks.extend(actual)

	def fire_starts(self, *a, **kwds):
		return self._generic_fire(*(("start",) + a), **kwds)

	def fire_finishs(self, *a, **kwds):
		return self._generic_fire(*(("finish",) + a), **kwds)

	def run(self, reporter, limiter=packages.AlwaysTrue):
		enabled = {}.fromkeys(["cats", "pkgs", "vers"], False)
		for var, attr in (("cats", ["category"]), ("pkgs", ["package"]), ("vers", ["fullver", "version", "rev"])):
			enabled[var] = bool(list(collect_package_restrictions(limiter, attr)))

		cats = enabled.pop("cats")
		pkgs = enabled.pop("pkgs")
		vers = enabled.pop("vers")

		# take the most specific, and disable everything less
		if vers:
			cats = pkgs = False
		elif pkgs:
			vers = True
			cats = False
		elif cats:
			pkgs = vers = True
		else:
			cats = pkgs = vers = True

		if self.first_run:
			self.init_arch_profiles()
			if cats:
				self.fire_starts("cat", self.cat_checks, self.repo)
			if pkgs:
				self.fire_starts("key", self.pkg_checks, self.repo)
			if vers:
				self.fire_starts("cpv", self.cpv_checks, self.repo)
		self.first_run = False
		
		# and... build 'er up.
		if any(check.uses_caches for check in self.cpv_checks + self.pkg_checks + self.cat_checks):
			pkg_checks = list(self.pkg_checks) + [_WipeQueryCache()]
		else:
			pkg_checks = self.pkg_checks
		i = self.repo.itermatch(limiter, sorter=sorted)
		if vers and self.cpv_checks:
			i = self.trigger_cpv_checks(i, reporter)
		if pkgs and pkg_checks:
			i = self.trigger_pkg_checks(pkg_checks, i, reporter)
		if cats and self.cat_checks:
			i = self.trigger_cat_checks(i, reporter)
		count = 0
		for x in i:
			count += 1

		return count
	
	def finish(self, reporter):
		self.fire_finishs("cat", self.cat_checks, reporter)
		self.fire_finishs("pkg", self.pkg_checks, reporter)
		self.fire_finishs("cpv", self.cpv_checks, reporter)
		
	def run_check(self, checks, payload, reporter, errmsg):
		for check in checks:
			try:
				if check.uses_caches:
					check.feed(payload, reporter, self)
				else:
					check.feed(payload, reporter)
			except SystemExit:
				raise
			except Exception, e:
				logging.error(errmsg % (check, e))
				del e

	def _generic_trigger_checks(self, checks, attr, iterable, reporter):
		afunc = operator.attrgetter(attr)
		l = [iterable.next()]
		yield l[0]
		lattr = afunc(l[0])
		for pkg in iterable:
			if lattr != afunc(pkg):
				self.run_check(checks, l, reporter, "check %s"+" "+attr+": '"+lattr+"' threw exception %s")
				l = [pkg]
				lattr = afunc(pkg)
			else:
				l.append(pkg)
			yield pkg
		self.run_check(checks, l, reporter, "check %s"+" "+attr+": '"+lattr+"' threw exception %s")

	def trigger_cat_checks(self, *args):
		return self._generic_trigger_checks(self.cat_checks, "category", *args)
	
	def trigger_pkg_checks(self, checks, *args):
		return self._generic_trigger_checks(checks, "package", *args)

	def trigger_cpv_checks(self, iterable, reporter):
		for pkg in iterable:
			self.run_check(self.cpv_checks, pkg, reporter, "check %s cpv: '"+str(pkg)+"' threw exception %s")
			yield pkg
	

class Result(object):
	
	description = None
	
	def __str__(self):
		try:
			return self.to_str()
		except NotImplementedError:
			return "result from %s" % self.__class__.__name__
	
	def to_str(self):
		raise NotImplementedError
	
	def to_xml(self):
		raise NotImplementedError


class Reporter(object):
	def __init__(self):
		self.reports = []
	
	def add_report(self, result):
		self.reports.append(result)

	def start(self):
		pass

	def finish(self):
		pass

class StrReporter(Reporter):
	def __init__(self, file_obj):
		self.handle = file_obj
	
	def add_report(self, result):
		self.handle.write("%s\n" % (result.to_str()))
	
class XmlReporter(Reporter):
	def __init__(self, file_obj):
		self.handle = file_obj

	def start(self):
		self.handle.write("<checks>\n")

	def add_report(self, result):
		self.handle.write("%s\n" % (result.to_xml()))

	def finish(self):
		self.handle.write("</checks>\n")


class MultiplexReporter(Reporter):
	def __init__(self, *reporters):
		if len(reporters) < 2:
			raise ValueError("need at least two reporters")
		self.reporters = tuple(reporters)
	
	def start(self):
		for x in self.reporters:
			x.start()
	
	def add_report(self, result):
		for x in self.reporters:
			x.add_report(result)
	
	def finish(self):
		for x in self.reporters:
			x.finish()
