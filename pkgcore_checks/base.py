# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: GPL2

repository_feed = "repo"
category_feed = "cat"
package_feed = "cat/pkg"
versioned_feed = "cat/pkg-ver"

known_feeds = (repository_feed, category_feed, package_feed,
    versioned_feed)

__all__ = ("package_feed, versioned_feed", "category_feed", "Feeder")

import itertools, operator

from pkgcore.restrictions.util import collect_package_restrictions
from pkgcore_checks import util
from pkgcore.util.mappings import OrderedDict
from pkgcore.util.containers import ProtectedSet
from pkgcore.restrictions import values, packages
from pkgcore.util.demandload import demandload
from itertools import chain
demandload(globals(), "logging "
    "pkgcore.config.profiles ")

# done as convience to checks. pylint: disable-msg=W0611,W0401
from pkgcore_checks.options import *


class template(object):
    """
    base template for a check
    
    @ivar feed_type: type of 'chunks' it should received, either repo_feed
        category_feed, package_feed, or versioned_feed
    @ivar requires: tuple of optparse.Option derivatives required to run 
        the check
    @ivar enabling_threshold: either unset (defaults to feed_type), or a
        feed type for when this check can be ran; useful for if a check
        only makes sense ran at the repo level, but needs only to iterate
        over a versioned feed
    @ivar disabled: either unset (thus enabled), or a boolean controlling
        whether a derivative of template is usable
    """
    feed_type = None
    requires = ()
    
    def __init__(self, options):
        self.options = options

    def start(self, repo, *a):
        pass

    def finish(self, reporter):
        pass
    
    def feed(self, chunk, reporter):
        raise NotImplementedError


class _WipeQueryCache(template):
    requires = query_cache_options
    feed_type = package_feed

    def __init__(self, options, enabling_threshold):
        template.__init__(self, options)
        self.enabling_threshold = enabling_threshold

    # protocol... pylint: disable-msg=W0613
    def feed(self, pkgs, reporter, feeder):
        feeder.query_cache.clear()


class _WipeEvaluateDepSetCaches(template):
    requires = query_cache_options
    feed_type = package_feed

    def __init__(self, options, enabling_threshold):
        template.__init__(self, options)
        self.enabling_threshold = enabling_threshold

    # protocol... pylint: disable-msg=W0613
    def feed(self, pkgs, reporter, feeder):
        feeder.pkg_evaluate_depsets_cache.clear()
        feeder.pkg_profiles_cache.clear()


class ForgetfulDict(dict):

    # protocol... pylint: disable-msg=W0613
    def __setitem__(self, key, val):
        return
    
    # protocol... pylint: disable-msg=W0613
    def update(self, other):
        return


class Feeder(object):

    def __init__(self, repo, options):
        self.options = options
        self.repo_checks = []
        self.cat_checks = []
        self.pkg_checks = []
        self.ver_checks = []
        self.repo = repo
        self.search_repo = options.target_repo
        self.profiles = {}
        self.profiles_inited = False
        self.pkg_evaluate_depsets_cache = {}
        self.pkg_profiles_cache = {}
        self.debug = options.debug
        self.desired_arches = getattr(self.options, "arches", None)

    def add_check(self, check):
        feed_type = getattr(check, "feed_type", None)
        if feed_type not in known_feeds:
            raise TypeError("check(%s) feed_type %s unknown" % 
                (check, feed_type))
        threshold = getattr(check, "enabling_threshold", feed_type)
        # check the enabling_threshold next.
        if threshold not in known_feeds:
            raise TypeError("check enabling_threshold %s %s unknown for %s" % 
                (threshold, check))

        if threshold == repository_feed:
            l = self.repo_checks
        elif threshold == category_feed:
            l = self.cat_checks
        elif threshold == package_feed:
            l = self.pkg_checks
        elif threshold == versioned_feed:
            l = self.ver_checks

        l.append(check(self.options))

    def clear_caches(self):
        self.profiles = {}

    def init_arch_profiles(self):
        if self.profiles_inited:
            return

        def norm_name(x):
            return '/'.join(y for y in x.split('/') if y)

        disabled = set(norm_name(x) for x in self.options.profiles_disabled)
        enabled = set(x for x in 
            (norm_name(y) for y in self.options.profiles_enabled)
            if x not in disabled)

        arch_profiles = {}
        if self.options.profiles_desc_enabled:
            d = \
                util.get_profiles_desc(self.options.profile_base_dir,
                    ignore_dev=self.options.profile_ignore_dev)
            
            for k, v in d.iteritems():
                l = [x for x in map(norm_name, v)
                    if not x in disabled]
                
                # wipe any enableds that are here already so we don't 
                # get a profile twice
                enabled.difference_update(l)
                if v:
                    arch_profiles[k] = l

        for x in enabled:
            p = self.options.profile_func(x)
            arch = p.arch
            if arch is None:
                raise pkgcore.config.profiles.ProfileException(
                    "profile %s lacks arch settings, unable to use it" % x)
            arch_profiles.setdefault(p.arch, []).append((x, p))
            
        for x in self.options.profiles_enabled:
            self.options.profile_func(x)

        self.official_arches = \
            util.get_repo_known_arches(self.options.profile_base_dir)

        if self.desired_arches is None:
            # copy it to be safe
            self.desired_arches = set(self.official_arches)

        self.global_insoluable = set()
        profile_filters = {}
        self.keywords_filter = {}
        profile_evaluate_dict = {}
        ignore_deprecated = self.options.profile_ignore_deprecated
        
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
            for profile_name in arch_profiles.get(k, []):
                if not isinstance(profile_name, basestring):
                    profile_name, profile = profile_name
                else:
                    profile = self.options.profile_func(profile_name)
                if ignore_deprecated and profile.deprecated:
                    continue
                mask = util.get_profile_mask(profile)
                virtuals = profile.virtuals(self.search_repo)
                # force all use masks to negated, and all other arches but this
                non_tristate = frozenset(list(self.official_arches) +
                    list(profile.use_mask) + list(profile.use_force))
                use_flags = frozenset([stable_key] + list(profile.use_force))
                
                package_use_force = profile.package_use_force
                package_use_mask  = profile.package_use_mask
                                
                # used to interlink stable/unstable lookups so that if 
                # unstable says it's not visible, stable doesn't try
                # if stable says something is visible, unstable doesn't try.
                stable_cache = set()
                unstable_insoluable = ProtectedSet(self.global_insoluable)

                # ensure keywords is last, else it triggers a metadata pull
                # filter is thus- not masked, and keywords match

                # virtual repo, flags, visibility filter, known_good, known_bad
                profile_filters[stable_key][profile_name] = \
                    [virtuals, package_use_mask, package_use_force,
                        use_flags, non_tristate, 
                        packages.AndRestriction(mask, stable_r), 
                        stable_cache, ProtectedSet(unstable_insoluable),
                        profile.package_provided_repo]
                profile_filters[unstable_key][profile_name] = \
                    [virtuals, package_use_mask, package_use_force,
                        use_flags, non_tristate,
                        packages.AndRestriction(mask, unstable_r), 
                        ProtectedSet(stable_cache), unstable_insoluable,
                        profile.package_provided_repo]
                
                for k in (stable_key, unstable_key):
                    profile_evaluate_dict.setdefault(k, {}).setdefault(
                        (non_tristate, use_flags), []).append(
                            (package_use_mask, package_use_force, profile_name))

            self.keywords_filter[stable_key] = stable_r
            self.keywords_filter[unstable_key] = packages.PackageRestriction(
                "keywords", 
                values.ContainmentMatch(unstable_key))

        self.arch_profiles = arch_profiles
        self.keywords_filter = OrderedDict((k, self.keywords_filter[k]) 
            for k in sorted(self.keywords_filter))
        self.profile_filters = profile_filters
        self.profile_evaluate_dict = profile_evaluate_dict
        self.profiles_inited = True

    def identify_profiles(self, pkg):
        return [(key, flags_dict) for key, flags_dict in
            self.profile_evaluate_dict.iteritems() if
            self.keywords_filter[key].match(pkg)]

    def identify_common_depsets(self, pkg, depset):
        pkey = pkg.key
        profiles = self.pkg_profiles_cache.get(pkg, None)
        if profiles is None:
            profiles = self.identify_profiles(pkg)
            self.pkg_profiles_cache[pkg] = profiles
        diuse = depset.known_conditionals
        collapsed = {}
        for key, flags_dict in profiles:
            for flags, profile_data in flags_dict.iteritems():
                # XXX optimize this
                empty_umd = None
                empty_ufd = None                
                for umd, ufd, profile_name in profile_data:
                    ur = umd.get(pkey, None)
                    if ur is None:
                        if empty_umd is None:
                            tri_flags = empty_umd = diuse.intersection(flags[0])
                        else:
                            tri_flags = empty_umd
                    else:
                        tri_flags = diuse.intersection(chain(flags[0],
                            *[v for restrict, v in 
                                ur.iteritems()
                                if restrict.match(pkg)]))
                    ur = ufd.get(pkey, None)
                    if ur is None:
                        if empty_ufd is None:
                            set_flags = empty_ufd = diuse.intersection(flags[1])
                        else:
                            set_flags = empty_ufd
                    else:
                        set_flags = diuse.intersection(chain(flags[1],
                            *[v for restrict, v in
                                ur.iteritems()
                                if restrict.match(pkg)]))

                    collapsed.setdefault((tri_flags, 
                        set_flags), []).append((key, profile_name, 
                            self.profile_filters[key][profile_name]))

        return [(depset.evaluate_depset(k[1], tristate_filter=k[0]), v)
            for k,v in collapsed.iteritems()]

    def collapse_evaluate_depset(self, pkg, attr, depset):
        depset_profiles = self.pkg_evaluate_depsets_cache.get((pkg, attr), None)
        if depset_profiles is None:
            depset_profiles = self.identify_common_depsets(pkg, depset)
            self.pkg_evaluate_depsets_cache[(pkg, attr)] = depset_profiles
        return depset_profiles

    def _generic_fire(self, attr, check_type, checks, *args):
        if not checks:
            return
        actual = []
        for check in checks:
            if attr == "start" and check_uses_profiles(check):
                self.init_arch_profiles()
                a = args + (self.global_insoluable, self.keywords_filter,
                    self.profile_filters)
            else:
                a = args
            try:
                getattr(check, attr)(*a)
                actual.append(check)
            except (SystemExit, KeyboardInterrupt):
                raise
            except Exception, e:
                logging.error("type %s, check %s failed running %s: %s" % 
                    (check_type, check, attr, e))
                if self.debug:
                    raise
                del e
        # rebuild the checks should any have failed
        for x in xrange(len(checks)):
            checks.pop()
        checks.extend(actual)

    def fire_starts(self, *a, **kwds):
        return self._generic_fire(*(("start",) + a), **kwds)

    def fire_finishes(self, *a, **kwds):
        return self._generic_fire(*(("finish",) + a), **kwds)

    @property
    def query_cache_enabled(self):
        return bool(getattr(self, "enable_query_cache", False))

    def run(self, reporter, limiter=packages.AlwaysTrue):

        enabled = {}.fromkeys(["cats", "pkgs", "vers"], False)

        for var, attr in (("cats", ["category"]), ("pkgs", ["package"]),
            ("vers", ["fullver", "version", "rev"])):

            enabled[var] = bool(list(collect_package_restrictions(limiter,
                attr)))

        cats = enabled.pop("cats")
        pkgs = enabled.pop("pkgs")
        vers = enabled.pop("vers")

        # take the most specific, and disable everything less
        repos = False
        if vers:
            cats = pkgs = False
        elif pkgs:
            vers = True
            cats = False
        elif cats:
            pkgs = vers = True
        else:
            repos = cats = pkgs = vers = True
        
        checks = []
        if repos:
            checks.extend(self.repo_checks)
        if cats:
            checks.extend(self.cat_checks)
        if pkgs:
            checks.extend(self.pkg_checks)
        if vers:
            checks.extend(self.ver_checks)

        translate = {"cat":category_feed, "pkg":package_feed,
            "ver":"version_feed"}

        if self.query_cache_enabled:
            self.query_cache = {}
            freq = translate[self.options.query_caching_freq]
            checks.append(_WipeQueryCache(self, freq))
            checks.append(_WipeEvaluateDepSetCaches(self, freq))
        
        # split them apart now, since the checks were pulled in by enabling
        # threshold
        repo_checks = [c for c in checks if c.feed_type == repository_feed]
        cat_checks =  [c for c in checks if c.feed_type == category_feed]
        pkg_checks =  [c for c in checks if c.feed_type == package_feed]
        ver_checks =  [c for c in checks if c.feed_type == versioned_feed]

        i = self.repo.itermatch(limiter, sorter=sorted)
        if ver_checks:
            self.fire_starts("ver", ver_checks, self.search_repo)
            i = self.trigger_ver_checks(ver_checks, i, reporter)

        if pkg_checks:
            self.fire_starts("key", pkg_checks, self.search_repo)
            i = self.trigger_pkg_checks(pkg_checks, i, reporter)

        if cat_checks:
            self.fire_starts("cat", cat_checks, self.search_repo)
            i = self.trigger_cat_checks(cat_checks, i, reporter)

        if repo_checks:
            self.fire_starts("repo", repo_checks, self.search_repo)
            i = self.trigger_repo_checks(repo_checks, i, reporter)

        count = 0
        for x in i:
            count += 1
        
        #and... unwind.
        if repo_checks:
            self.fire_finishes("repo", repo_checks, reporter)

        if cat_checks:
            self.fire_finishes("cat", cat_checks, reporter)

        if pkg_checks:
            self.fire_finishes("pkg", pkg_checks, reporter)

        if ver_checks:
            self.fire_finishes("ver", ver_checks, reporter)

        return count

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
                if self.debug:
                    raise
                logging.error(errmsg % (check, e))
                del e

    def _generic_trigger_checks(self, checks, attr, iterable, reporter):
        checks = tuple((check_uses_query_cache(c), c) for c in checks)
        grouping_iter = itertools.groupby(iterable, operator.attrgetter(attr))
        for key, pkgs in grouping_iter:
            # convert the iter to a tuple; note that using a caching_iter
            # may be better here, but need to evaluate performance affects
            # before hand
            pkgs = tuple(pkgs)
            # XXX string generation per call is inneficient here.
            self.run_check(checks, pkgs, reporter,
                "check %s"+" "+attr+": '"+key+"' threw exception %s")
            for pkg in pkgs:
                yield pkg

    def trigger_repo_checks(self, checks, iterable, reporter):
        checks = tuple((check_uses_query_cache(check), check)
            for check in checks)
        repo_pkgs = list(iterable)
        self.run_check(checks, repo_pkgs, reporter,
            "check %s cpv: repo level check' threw exception %s")
        for pkg in repo_pkgs:
            yield pkg

    def trigger_cat_checks(self, checks, iterable, reporter):
        return self._generic_trigger_checks(checks, "category", iterable,
            reporter)
    
    def trigger_pkg_checks(self, checks, iterable, reporter):
        return self._generic_trigger_checks(checks, "package", iterable,
            reporter)

    def trigger_ver_checks(self, checks, iterable, reporter):
        checks = tuple((check_uses_query_cache(check), check)
            for check in checks)
        for pkg in iterable:
            self.run_check(checks, pkg, reporter,
                "check %s cpv: '"+str(pkg)+"' threw exception %s")
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

    def _store_cp(self, pkg):
        self.category = pkg.category
        self.package = pkg.package
    
    def _store_cpv(self, pkg):
        self._store_cp(pkg)
        self.version = pkg.fullver


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
        self.first_report = True
    
    def add_report(self, result):
        if self.first_report:
            self.handle.write("\n")
            self.first_report = False
        self.handle.write("%s\n" % (result.to_str()))

    def finish(self):
        if not self.first_report:
            self.handle.write("\n")

    
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
