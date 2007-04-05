# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: GPL2

from snakeoil.compatibility import any
from pkgcore_checks import base, addons
from snakeoil.iterables import caching_iter
from pkgcore.restrictions import boolean
from pkgcore.ebuild.atom import atom
from pkgcore.package import virtual
from pkgcore_checks.util import get_cpvstr

from snakeoil.demandload import demandload
demandload(globals(),
    'urllib:urlopen',
    'snakeoil.xml:escape',
    'pkgcore.log:logger',
)


class SuggestRemoval(base.Result):
    
    """pkg isn't ported, stablize the targets and it can likely go away"""
    
    __slots__ = ("category", "package", "version", "ported")

    threshold = base.versioned_feed

    def __init__(self, pkg, ported):
        base.Result.__init__(self)
        self._store_cpv(pkg)
        self.ported = tuple(get_cpvstr(x) for x in ported)

    @property
    def short_desc(self):
        return "version is unported, suggest removal for one of the ported " \
            "versions: [ %s ]" % ', '.join(self.ported)
    

class BadRange(base.Result):
    
    """
    look for virtual/x11 atoms that don't intersect =virtual/x11-6.9
    """
    
    __slots__ = ("category", "package", "version", "attr", "atoms")

    threshold = base.versioned_feed

    def __init__(self, pkg, attr, atom_inst):
        base.Result.__init__(self)
        self._store_cpv(pkg)
        self.attr = attr
        self.atoms = tuple(str(x) for x in atom_inst)
    
    @property
    def short_desc(self):
        return "%s: virtual/x11 atoms must match version 6.9: %s" % (
            self.attr, ', '.join(self.atoms))


class NotPorted(base.Result):
    
    """standalone virtual/x11 atom, not ported."""
    
    __slots__ = ("category", "package", "version", "attr", "or_block")

    threshold = base.versioned_feed

    def __init__(self, pkg, attr, or_block):
        base.Result.__init__(self)
        self._store_cpv(pkg)
        self.attr = attr
        self.or_block = or_block
    
    @property
    def short_desc(self):
        return "%s: has standalone virtual/x11 in an OR block" % self.attr


class VisibilityCausedNotPorted(base.Result):
    
    """
    ported, but due to visibility (mask'ing/keywords), knocked back to
    effectively not ported
    """
    
    __slots__ = ("category", "package", "version", "attr", "keyword",
        "profile", "failed")

    threshold = base.versioned_feed

    def __init__(self, pkg, keyword, profile, attr, failed):
        base.Result.__init__(self)
        self._store_cpv(pkg)
        self.attr = attr
        self.keyword = keyword
        self.profile = profile
        self.failed = tuple(str(x) for x in failed)
    
    @property
    def short_desc(self):
        return "attr(%s): keyword(%s): profile(%s): visibility induced " \
            " unported, fix via [ %s ]" % (self.attr, self.keyword, 
            self.profile, ', '.join(self.failed))


class ModularXPortingReport(base.Template):

    """modular X porting report.
    Scans for dependencies that require monolithic X, or via visibility 
    limiters from profiles, are forced to use monolithic X
    """
    feed_type = base.package_feed
    required_addons = (
        addons.ArchesAddon, addons.QueryCacheAddon, addons.EvaluateDepSetAddon)
    known_results = (SuggestRemoval, BadRange, NotPorted,
        VisibilityCausedNotPorted)

    valid_modx_pkgs_url = \
        "http://www.gentoo.org/proj/en/desktop/x/x11/modular-x-packages.txt"

    @classmethod
    def mangle_option_parser(cls, parser):
        parser.add_option(
            '--mod-x-packages',
            help='location to cache %s' % (cls.valid_modx_pkgs_url,))

    def __init__(self, options, arches, query_cache, depset_cache):
        base.Template.__init__(self, options)
        self.query_cache = query_cache.query_cache
        self.depset_cache = depset_cache
        self.arches = frozenset(x.lstrip("~") for x in options.arches)
        # use 7.1 so it catches any >7.0
        self.x7 = virtual.package(None, "virtual/x11-7.1")
        self.x6 = virtual.package(None, "virtual/x11-6.9")
        if self.options.mod_x_packages is not None:
            try:
                package_list = open(self.options.mod_x_packages, 'r')
            except (IOError, OSError), e:
                logger.warn(
                    'modular X package file cannot be opened (%s), refetching',
                    e)
                package_list = list(urlopen(self.valid_modx_pkgs_url))
                try:
                    f = open(self.options.mod_x_packages, 'w')
                    for line in package_list:
                        f.write(line)
                except (IOError, OSError), e:
                    logger.warn(
                        'modular X package file could not be written (%s)', e)
        else:
            package_list = urlopen(self.valid_modx_pkgs_url)
        self.valid_modx_keys = frozenset(x for x in
            (y.strip() for y in package_list) if
                x and x != "virtual/x11")

    def feed(self, pkgset, reporter):
        # query_cache gets caching_iter partial repo searches shoved into it-
        # reason is simple, it's likely that versions of this pkg probably 
        # use similar deps- so we're forcing those packages that were
        # accessed for atom matching to remain in memory.
        # end result is less going to disk
        unported = []
        for pkg in pkgset:
            self.check_pkg(pkg, reporter, unported)

        if unported:
            for u in unported:
                l = [pkg for pkg in pkgset if pkg not in unported]
                if l:
                    reporter.add_report(SuggestRemoval(u, l))

    def check_pkg(self, pkg, reporter, unported):
        failed = []

        bool_or = boolean.OrRestriction
        for attr, depset in (("depends", pkg.depends),
            ("rdepends", pkg.rdepends), ("pdepends", pkg.post_rdepends)):
            stack = [depset.evaluate_depset([], tristate_filter=[]
                ).restrictions]
            bad_range = set()
            bad_blocks = set()
            while stack:
                for a in stack.pop(-1):
                    if isinstance(a, atom):
                        if a.key == "virtual/x11" and not a.blocks:
                            if not a.match(self.x6):
                                bad_range.add(a)
                            bad_blocks.add((a,))
                    elif isinstance(a, bool_or):
                        for block in a.iter_dnf_solutions():
                            i = iter(block)
                            for x in i:
                                if x.blocks:
                                    continue
                                if x.key == "virtual/x11":
                                    break
                            else:
                                continue
                            for x in i:
                                if not x.blocks and \
                                    x.key in self.valid_modx_keys:
                                    break
                            else:
                                for or_block in a.cnf_solutions():
                                    if not any(True for x in or_block if
                                        x.key == "virtual/x11"
                                        and not x.blocks):
                                        continue

                                    if any(True for x in or_block if
                                        x.key in self.valid_modx_keys
                                        and not x.blocks):
                                        break
                                else:
                                    # standalone virtual/x11
                                    bad_blocks.add(tuple(block))
                                break
                    else:
                        stack.append(a.restrictions)
            if bad_range:
                reporter.add_report(BadRange(pkg, attr, sorted(bad_range)))
            if bad_blocks:
                for bad in sorted(bad_blocks):
                    reporter.add_report(NotPorted(pkg, attr, bad))
            if bad_range or bad_blocks:
                failed.append(attr)
                    
        if failed:
            unported.append(pkg)
        
        if len(failed) == 2:
            # no point in trying it out, will fail anyways
            return
                
        skip_depends = "depends" in failed
        skip_rdepends = "rdepends" in failed
        skip_pdepends = "pdepends" in failed
        del failed

        # ok heres the rules of the road.
        # valid: || ( modx <virtual/x11-7 ), || ( modx virtual/x11 )
        # not valid: >=virtual/x11-7 anywhere, virtual/x11 floating
        # not valid: x11-base/xorg-x11 floating

        if not skip_depends:
            for edepset, profiles in \
                self.depset_cache.collapse_evaluate_depset(pkg, "depends",
                pkg.depends):
                self.process_depset(pkg, "depends", edepset, profiles,
                                    reporter)

        if not skip_rdepends:
            for edepset, profiles in \
                self.depset_cache.collapse_evaluate_depset(pkg, "rdepends",
                pkg.rdepends):
                self.process_depset(pkg, "rdepends", edepset, profiles,
                                    reporter)

        if not skip_pdepends:
            for edepset, profiles in self.depset_cache.collapse_evaluate_depset(
                pkg, "post_rdepends", pkg.post_rdepends):
                self.process_depset(pkg, "post_rdepends", edepset, profiles,
                                    reporter)
                
    def process_depset(self, pkg, attr, depset, profiles, reporter):

        csolutions = depset.cnf_solutions()
        failed = set()
        for profile in profiles:
            failed.clear()
            cache = profile.cache
            insoluable = profile.insoluable
            visible = profile.visible
            for or_block in csolutions:
                if not any(True for x in or_block if x.key == "virtual/x11"):
                    continue
            
                # we know a virtual/x11 is in this options.
                # better have a modx node in options, else it's bad.
                modx_candidates = [x for x in or_block if
                    x.key in self.valid_modx_keys]
                for a in modx_candidates:
                    if a.blocks:
                        # weird.
                        continue
                    h = str(a)
                    if h in insoluable:
                        continue
                    elif h in cache:
                        break
                    elif h not in self.query_cache:
                        self.query_cache[h] = caching_iter(
                            self.options.search_repo.itermatch(a))
                    # if a provider is visible, good to go.
                    if any(True for pkg in self.query_cache[h] if visible(pkg)):
                        cache.add(h)
                        break
                    else:
                        insoluable.add(h)
                else:
                    failed.update(modx_candidates)
            if failed:
                reporter.add_report(VisibilityCausedNotPorted(pkg,
                    profile.key, profile.name, attr, sorted(failed)))
