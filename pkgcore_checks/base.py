# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: GPL2

category_feed = "cat"
package_feed = "cat/pkg"
versioned_feed = "cat/pkg-ver"

__all__ = ("package_feed, versioned_feed", "category_feed", "Feeder")

import optparse
import itertools, operator

from pkgcore.restrictions import packages
from pkgcore.restrictions.util import collect_package_restrictions
from pkgcore_checks import util
from pkgcore.util.mappings import OrderedDict
from pkgcore.util.containers import ProtectedSet
from pkgcore.util.compatibility import any
from pkgcore.util.currying import pre_curry
from pkgcore.restrictions import values, packages
from pkgcore.util.demandload import demandload
demandload(globals(), "logging os "
	"pkgcore.fs.util:abspath "
	"pkgcore.ebuild:repository ")


class FinalizingOption(optparse.Option):

	def __init__(self, *args, **kwds):
		f = kwds.pop("finalizer", None)
		optparse.Option.__init__(self, *args, **kwds)
		if f is not None:
			self.finalize = pre_curry(f, self)

	def finalize(self, options, runner):
		raise NotImplementedError(self, "finalize")


default_arches = ["x86", "x86-fbsd", "amd64", "ppc", "ppc-macos", "ppc64",
	"sparc", "mips", "arm", "hppa", "m68k", "ia64", "s390", "sh", "alpha"]
default_arches = tuple(sorted(default_arches))

def _record_arches(attr, option, opt_str, value, parser):
	setattr(parser.values, attr, tuple(value.split(",")))

arches_option = optparse.Option("-a", "--arches", action='callback', callback=pre_curry(_record_arches, "arches"), type='string',  
	default=default_arches, help="comma seperated list of what arches to run, defaults to %s" % ",".join(default_arches))
arches_options = (arches_option,)


def enable_query_caching(option_inst, options, runner):
	runner.enable_query_cache = True

query_cache_options = \
	(FinalizingOption("--reset-caching-per-category", action='store_const', dest='query_caching_freq', 
		const='cat', finalizer=enable_query_caching,
		help="clear query caching after every category (defaults to every package)"),
	optparse.Option("--reset-caching-per-package", action='store_const', dest='query_caching_freq',
		const='pkg', default='pkg',
		help="clear query caching after ever package (this is the default)"),
	optparse.Option("--reset-caching-per-version", action='store_const', dest='query_caching_freq',
		const='ver',
		help="clear query caching after ever version (defaults to every package)"))


def check_uses_query_cache(check):
	return any(x in query_cache_options for x in check.requires)


def overlay_finalize(option_inst, options, runner):
	if options.metadata_src_repo is None:
		options.repo_base = None
		options.src_repo = options.target_repo
		return

	conf = options.pkgcore_conf
	try:
		repo = conf.repo[options.metadata_src_repo]
	except KeyError:
		raise optparse.OptionValueError("overlayed-repo %r isn't a known repo" % profile_src)

	if not isinstance(repo, repository.UnconfiguredTree):
		raise optparse.OptionValueError("profile-repo %r isn't an pkgcore.ebuild.repository.UnconfiguredTree instance; must specify a raw ebuild repo, not type %r: %r" %
			(repo.__class__, repo))
	options.src_repo = repo
	options.repo_base = abspath(repo.base)


overlay_options = (FinalizingOption("-r", "--overlayed-repo", action='store', type='string', dest='metadata_src_repo',
	finalizer=overlay_finalize,
	help="if the target repository is an overlay, specify the repository name to pull profiles/license from"),)
	

def get_repo_base(options, throw_error=True, repo=None):
	if getattr(options, "repo_base", None) is not None:
		return options.repo_base
	if repo is None:
		repo = options.target_repo
	if throw_error:
		if not isinstance(repo, repository.UnconfiguredTree):
			raise optparse.OptionValueError("target repo %r isn't a pkgcore.ebuild.repository.UnconfiguredTree instance; "
				"must specify the PORTDIR repo via --overlayed-repo" % repo)

	return getattr(repo, "base", None)


def profile_finalize(option_inst, options, runner):
	runner.enable_profiles = True
	profile_loc = getattr(options, "profile_dir", None)

	if profile_loc is not None:
		abs_profile_loc = abspath(profile_loc)
		if not os.path.isdir(abs_profile_loc):
			raise optparse.OptionValueError("profile-base location %r doesn't exist/isn't a dir" % profile_loc)
		
		options.profile_func = pre_curry(util.get_profile_from_path, abs_profile_loc)
		options.profile_base_dir = abs_profile_loc
		return


	profile_base = os.path.join(get_repo_base(options), "profiles")
	if not os.path.isdir(profile_base):
		raise optparse.OptionValueError("repo %r lacks a profiles directory" % options.src_repo)

	options.profile_func = pre_curry(util.get_profile_from_repo, options.target_repo)
	options.profile_base_dir = abspath(profile_base)


profile_options = \
	(FinalizingOption("--profile-base", action='store', type='string',
		finalizer=profile_finalize, dest="profile_dir", default=None,
		help="filepath to base profiles directory"),)


def check_uses_profiles(check):
	return any(x in profile_options for x in check.requires)


class template(object):
	feed_type = None
	requires = ()

	def __init__(self, options):
		pass

	def start(self, repo):
		pass

	def finish(self, reporter):
		pass
	
	def process(self, chunk, reporter):
		raise NotImplementedError


class _WipeQueryCache(template):
	requires = query_cache_options
	feed_type = package_feed

	def feed(self, pkgs, reporter, feeder):
		feeder.query_cache.clear()


class _WipeEvaluateDepSetCaches(template):
	requires = query_cache_options
	feed_type = package_feed

	def feed(self, pkgs, reporter, feeder):
		feeder.pkg_evaluate_depsets_cache.clear()
		feeder.pkg_profiles_cache.clear()


class ForgetfulDict(dict):

	def __setitem__(self, key, attr):
		return
	
	def update(self, other):
		return


class Feeder(object):

	def __init__(self, repo, options):
		self.options = options
		self.pkg_checks = []
		self.cat_checks = []
		self.cpv_checks = []
		self.first_run = True
		self.repo = repo
		self.profiles = {}
		self.profiles_inited = False
		self.pkg_evaluate_depsets_cache = {}
		self.pkg_profiles_cache = {}

	@property
	def desired_arches(self):
		return self.options.arches

	def add_check(self, check):
		feed_type = getattr(check, "feed_type", None)
		if feed_type == category_feed:
			self.cat_checks.append(check(self.options))
		elif feed_type == package_feed:
			self.pkg_checks.append(check(self.options))
		elif feed_type == versioned_feed:
			self.cpv_checks.append(check(self.options))
		else:
			raise TypeError("check feed_type %s unknown for %s" % (feed_type, check))

	def clear_caches(self):
		self.profiles = {}

	def init_arch_profiles(self):
		if self.profiles_inited:
			return
		self.arch_profiles = util.get_profiles_desc(self.repo)

		if self.desired_arches is None:
			self.desired_arches = util.get_repo_known_arches(self.options.profile_src)

		self.global_insoluable = set()
		profile_filters = {}
		self.keywords_filter = {}
		profile_evaluate_dict = {}
		
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
				profile = self.options.profile_func(profile_name)
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
				
				for k in (stable_key, unstable_key):
					profile_evaluate_dict.setdefault(k, {}).setdefault((non_tristate, use_flags), []).append(profile_name)

			self.keywords_filter[stable_key] = stable_r
			self.keywords_filter[unstable_key] = packages.PackageRestriction("keywords", 
				values.ContainmentMatch(unstable_key))

		self.keywords_filter = OrderedDict((k, self.keywords_filter[k]) for k in sorted(self.keywords_filter))
		self.profile_filters = profile_filters
		self.profile_evaluate_dict = profile_evaluate_dict
		self.profiles_inited = True

	def identify_profiles(self, pkg):
		return [(key, flags_dict) for key, flags_dict in self.profile_evaluate_dict.iteritems() if self.keywords_filter[key].match(pkg)]

	def collapse_evaluate_depset(self, pkg, attr, depset):
		depset_profiles = self.pkg_evaluate_depsets_cache.get((pkg, attr), None)
		if depset_profiles is None:
			profiles = self.pkg_profiles_cache.get(pkg, None)
			if profiles is None:
				profiles = self.pkg_profiles_cache[pkg] = self.identify_profiles(pkg)
			diuse = depset.known_conditionals
			collapsed = {}
			for key, flags_dict in profiles:
				for flags, profile_names in flags_dict.iteritems():
					tri_flags = diuse.difference(flags[0])
					set_flags = diuse.intersection(flags[1])
					collapsed.setdefault((tri_flags, set_flags), []).extend((key, profile, self.profile_filters[key][profile]) for profile in profile_names)
			depset_profiles = self.pkg_evaluate_depsets_cache[(pkg, attr)] = [(depset.evaluate_depset(k[1], tristate_filter=v[0][2][2]), v) for k,v in collapsed.iteritems()]
		return depset_profiles

	def _generic_fire(self, attr, check_type, checks, *args):
		if not checks:
			return
		actual = []
		for check in checks:
			if attr == "start" and check_uses_profiles(check):
				a = args + (self.global_insoluable, self.keywords_filter, self.profile_filters)
			else:
				a = args
			try:
				getattr(check, attr)(*a)
				actual.append(check)
			except (SystemExit, KeyboardInterrupt):
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

	@property
	def query_cache_enabled(self):
		return bool(getattr(self, "enable_query_cache", False))

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
		
		cat_checks = list(self.cat_checks)
		pkg_checks = list(self.pkg_checks)
		cpv_checks = list(self.cpv_checks)

		# and... build 'er up.
		if self.query_cache_enabled:
			self.query_cache = {}
			l = [_WipeQueryCache(self), _WipeEvaluateDepSetCaches(self)]
			if self.options.query_caching_freq == "cat":
				cat_checks += l
			elif self.options.query_caching_freq == "pkg":
				pkg_checks += l
			elif self.options.query_caching_freq == "ver":
				cpv_checks += l
			del l
		
		i = self.repo.itermatch(limiter, sorter=sorted)
		if vers and cpv_checks:
			i = self.trigger_ver_checks(cpv_checks, i, reporter)
		if pkgs and pkg_checks:
			i = self.trigger_pkg_checks(pkg_checks, i, reporter)
		if cats and cat_checks:
			i = self.trigger_cat_checks(cat_checks, i, reporter)
		count = 0
		for x in i:
			count += 1

		return count
	
	def finish(self, reporter):
		self.fire_finishs("cat", self.cat_checks, reporter)
		self.fire_finishs("pkg", self.pkg_checks, reporter)
		self.fire_finishs("cpv", self.cpv_checks, reporter)
		
	def run_check(self, checks, payload, reporter, errmsg):
		for requires_cache, check in checks:
			try:
				if requires_cache:
					check.feed(payload, reporter, self)
				else:
					check.feed(payload, reporter)
			except (SystemExit, KeyboardInterrupt):
				raise
			except Exception, e:
				logging.error(errmsg % (check, e))
				del e

	def _generic_trigger_checks(self, checks, attr, iterable, reporter):
		checks = tuple((check_uses_query_cache(c), c) for c in checks)
		grouping_iter = itertools.groupby(iterable, operator.attrgetter(attr))
		for key, pkgs in grouping_iter:
			# convert the iter to a tuple; note that using a caching_iter may be better here,
			# but need to evaluate performance affects before hand
			pkgs = tuple(pkgs)
			self.run_check(checks, pkgs, reporter, "check %s"+" "+attr+": '"+key+"' threw exception %s")
			for pkg in pkgs:
				yield pkg

	def trigger_cat_checks(self, checks, iterable, reporter):
		return self._generic_trigger_checks(checks, "category", iterable, reporter)
	
	def trigger_pkg_checks(self, checks, iterable, reporter):
		return self._generic_trigger_checks(checks, "package", iterable, reporter)

	def trigger_ver_checks(self, checks, iterable, reporter):
		checks = tuple((check_uses_query_cache(check), check) for check in checks)
		for pkg in iterable:
			self.run_check(checks, pkg, reporter, "check %s cpv: '"+str(pkg)+"' threw exception %s")
			yield pkg
	

class Result(object):

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
