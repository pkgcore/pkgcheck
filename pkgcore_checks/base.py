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
demandload(globals(), "logging "
    "pkgcore.util:currying "
    "pkgcore.config.profiles ")


class template(object):
    """
    base template for a check
    
    @ivar feed_type: type of 'chunks' it should received, either repo_feed
        category_feed, package_feed, or versioned_feed
    @ivar required_addons: sequence of addons.Addon derivatives required
        to run the check
    @ivar enabling_threshold: either unset (defaults to feed_type), or a
        feed type for when this check can be ran; useful for if a check
        only makes sense ran at the repo level, but needs only to iterate
        over a versioned feed
    @ivar disabled: either unset (thus enabled), or a boolean controlling
        whether a derivative of template is usable
    """
    feed_type = None
    required_addons = ()

    def __init__(self, options):
        self.options = options

    def start(self, repo, **kwargs):
        pass

    def finish(self, reporter, **kwargs):
        pass

    def feed(self, chunk, reporter, **kwargs):
        raise NotImplementedError


class ForgetfulDict(dict):

    def __setitem__(self, key, val):
        return

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
        self.search_repo = options.search_repo
        self.debug = options.debug

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

        l.append(check)

    def _generic_fire(self, attr, check_type, checks, *args):
        if not checks:
            return
        actual = []
        hook_name = 'extra_%s_kwargs' % (attr,)
        for check in checks:
            kwargs = {}
            for addon in self.options.addons:
                if addon.__class__ in check.required_addons:
                    kwargs.update(getattr(addon, hook_name)())
            try:
                getattr(check, attr)(*args, **kwargs)
                actual.append(check)
            except (SystemExit, KeyboardInterrupt):
                raise
            except Exception:
                logging.exception("type %s, check %s failed running %s" %
                                  (check_type, check, attr))
                if self.debug:
                    raise
        # rebuild the checks should any have failed
        checks[:] = []
        checks.extend(actual)

    def fire_starts(self, *a, **kwds):
        return self._generic_fire(*(("start",) + a), **kwds)

    def fire_finishes(self, *a, **kwds):
        return self._generic_fire(*(("finish",) + a), **kwds)

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

        for addon in self.options.addons:
            extras = addon.start()
            if extras:
                checks.extend(extras)

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
        for check, func in checks:
            try:
                func(payload, reporter)
            except (SystemExit, KeyboardInterrupt):
                raise
            except Exception:
                if self.debug:
                    raise
                logging.exception(errmsg % (check,))

    def _curry_addon_args(self, check):
        extra_kwargs = dict()
        for addon in self.options.addons:
            if addon.__class__ in check.required_addons:
                extra_kwargs.update(addon.extra_feed_kwargs())
        if extra_kwargs:
            return currying.partial(check.feed, **extra_kwargs)
        else:
            return check.feed

    def _generic_trigger_checks(self, checks, attr, iterable, reporter):
        checks = tuple((c, self._curry_addon_args(c)) for c in checks)
        grouping_iter = itertools.groupby(iterable, operator.attrgetter(attr))
        for key, pkgs in grouping_iter:
            # convert the iter to a tuple; note that using a caching_iter
            # may be better here, but need to evaluate performance affects
            # before hand
            pkgs = tuple(pkgs)
            # XXX string generation per call is inneficient here.
            self.run_check(checks, pkgs, reporter,
                           "check %s "+attr+": '"+key+"' threw exception")
            for pkg in pkgs:
                yield pkg

    def trigger_repo_checks(self, checks, iterable, reporter):
        checks = tuple((c, self._curry_addon_args(c)) for c in checks)
        repo_pkgs = list(iterable)
        self.run_check(checks, repo_pkgs, reporter,
            "check %s cpv: repo level check' threw exception")
        for pkg in repo_pkgs:
            yield pkg

    def trigger_cat_checks(self, checks, iterable, reporter):
        return self._generic_trigger_checks(checks, "category", iterable,
            reporter)
    
    def trigger_pkg_checks(self, checks, iterable, reporter):
        return self._generic_trigger_checks(checks, "package", iterable,
            reporter)

    def trigger_ver_checks(self, checks, iterable, reporter):
        checks = tuple((c, self._curry_addon_args(c)) for c in checks)
        for pkg in iterable:
            self.run_check(checks, pkg, reporter,
                "check %s cpv: '"+str(pkg)+"' threw exception")
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

    def __init__(self, out):
        """Initialize.

        @type out: L{pkgcore.util.formatters.Formatter}.
        """
        self.out = out
        self.first_report = True

    def add_report(self, result):
        if self.first_report:
            self.out.write()
            self.first_report = False
        self.out.write(result.to_str())

    def finish(self):
        if not self.first_report:
            self.out.write()


class XmlReporter(Reporter):

    def __init__(self, out):
        """Initialize.

        @type out: L{pkgcore.util.formatters.Formatter}.
        """
        self.out = out

    def start(self):
        self.out.write('<checks>')

    def add_report(self, result):
        self.out.write(result.to_xml())

    def finish(self):
        self.out.write('</checks>')


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
