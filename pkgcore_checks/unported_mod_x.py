# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: GPL2

from pkgcore.util.compatibility import any
from pkgcore.util.demandload import demandload
from pkgcore_checks import base, addons
from pkgcore.util.iterables import caching_iter
from pkgcore.restrictions import boolean
from pkgcore.ebuild.atom import atom
from pkgcore.package import virtual
from pkgcore_checks.util import get_cpvstr
demandload(globals(), "pkgcore.util.xml:escape")
demandload(globals(), "urllib:urlopen")


class ModularXPortingReport(base.Template):

    """modular X porting report.
    Scans for dependencies that require monolithic X, or via visibility 
    limiters from profiles, are forced to use monolithic X
    """
    feed_type = base.package_feed
    required_addons = (
        addons.ArchesAddon, addons.QueryCacheAddon, addons.EvaluateDepSetAddon)

    valid_modx_pkgs_url = \
        "http://www.gentoo.org/proj/en/desktop/x/x11/modular-x-packages.txt"

    def __init__(self, options, arches, query_cache, depset_cache):
        base.Template.__init__(self, options)
        self.query_cache = query_cache.query_cache
        self.depset_cache = depset_cache
        self.arches = frozenset(x.lstrip("~") for x in options.arches)
        # use 7.1 so it catches any >7.0
        self.x7 = virtual.package(None, "virtual/x11-7.1")
        self.x6 = virtual.package(None, "virtual/x11-6.9")
        self.valid_modx_keys = frozenset(x for x in
            (y.strip() for y in urlopen(self.valid_modx_pkgs_url)) if
                x and x != "virtual/x11")

    def feed(self, pkgsets, reporter):
        # query_cache gets caching_iter partial repo searches shoved into it-
        # reason is simple, it's likely that versions of this pkg probably 
        # use similar deps- so we're forcing those packages that were
        # accessed for atom matching to remain in memory.
        # end result is less going to disk
        for pkgset in pkgsets:
            yield pkgset

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
        
        ported_status = False
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
                                        ported_status = True
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
            for edepset, profiles in self.depset_cache.collapse_evaluate_depset(
                pkg, "depends", pkg.depends):
                self.process_depset(pkg, "depends", edepset, profiles,
                                    reporter)

        if not skip_rdepends:
            for edepset, profiles in self.depset_cache.collapse_evaluate_depset(
                pkg, "rdepends", pkg.rdepends):
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
        for key, profile_name, data in profiles:
            failed.clear()
            virtuals, puse_mask, puse_flags, flags, non_tristate, vfilter, \
                cache, insoluable, pprovided = data
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
                            self.options.target_repo.itermatch(a))
                    if any(True for pkg in self.query_cache[h] if
                        vfilter.match(pkg)):
                        # one is visible.
                        cache.add(h)
                        break
                    else:
                        insoluable.add(h)
                else:
                    failed.update(modx_candidates)
            if failed:
                reporter.add_report(VisibilityCausedNotPorted(pkg, key,
                    profile_name, attr, sorted(failed)))


class SuggestRemoval(base.Result):
    
    """pkg isn't ported, stablize the targets and it can likely go away"""
    
    __slots__ = ("category", "package", "version", "ported")
    def __init__(self, pkg, ported):
        base.Result.__init__(self)
        self._store_cpv(pkg)
        self.ported = tuple(get_cpvstr(x) for x in ported)
    
    def to_str(self):
        return "%s/%s-%s: is unported, potentially remove for [ %s ]" \
            % (self.category, self.package, self.version,
                ", ".join(self.ported))
    
    def to_xml(self):
        return \
"""<check name="%s">
    <category>%s</category>
    <package>%s</package>
    <version>%s</version>
    <msg>unported, suggest replacing via: %s</msg>
</check>""" % (self.__class__.__name__, self.category, self.package,
    self.version, escape(", ".join(self.ported)))


class BadRange(base.Result):
    
    """
    look for virtual/x11 atoms that don't intersect =virtual/x11-6.9
    """
    
    __slots__ = ("category", "package", "version", "attr", "atom")
    def __init__(self, pkg, attr, atom_inst):
        base.Result.__init__(self)
        self._store_cpv(pkg)
        self.attr = attr
        self.atoms = tuple(str(x) for x in atom_inst)
    
    def to_str(self):
        return "%s/%s-%s: attr(%s): atoms don't match 6.9: [ %s ]" % \
            (self.category, self.package, self.version, self.attr, 
                ", ".join(self.atoms))
    
    def to_xml(self):
        return \
"""<check name="%s">
    <category>%s</category>
    <package>%s</package>
    <version>%s</version>
    <msg>attr %s has atoms %s, which do not match virtual/x11-6.9</msg>
</check>""" % (self.__class__.__name__, self.category, self.package,
    self.version, self.attr, escape(", ".join(self.atoms)))


class NotPorted(base.Result):
    
    """standalone virtual/x11 atom, not ported."""
    
    __slots__ = ("category", "package", "version", "attr", "or_block")

    def __init__(self, pkg, attr, or_block):
        base.Result.__init__(self)
        self._store_cpv(pkg)
        self.attr = attr
        self.or_block = or_block
    
    def to_str(self):
        return "%s/%s-%s: attr(%s): not ported, standalone virtual/x11 atom " \
            "detected in an or_block" % (self.category,
                self.package, self.version, self.attr)
    
    def to_xml(self):
        return \
"""<check name="%s">
    <category>%s</category>
    <package>%s</package>
    <version>%s</version>
    <msg>attr %s, standalone virtual/x11 atom detected in an or_block"</msg>
</check>""" % (self.__class__.__name__, self.category, self.package,
    self.version, self.attr)


class VisibilityCausedNotPorted(base.Result):
    
    """
    ported, but due to visibility (mask'ing/keywords), knocked back to
    effectively not ported
    """
    
    __slots__ = ("category", "package", "version", "attr", "keyword",
        "profile", "failed")

    def __init__(self, pkg, keyword, profile, attr, failed):
        base.Result.__init__(self)
        self._store_cpv(pkg)
        self.attr = attr
        self.keyword = keyword
        self.profile = profile
        self.failed = tuple(str(x) for x in failed)
    
    def to_str(self):
        return "%s/%s-%s: %s %s %s: visibility induced unported: fix via " \
            "making visible [ %s ]" % \
            (self.category, self.package, self.version, self.attr,
                self.keyword, self.profile, ", ".join(self.failed))
    
    def to_xml(self):
        return \
"""<check name="%s">
    <category>%s</category>
    <package>%s</package>
    <version>%s</version>
    <keyword>%s</keyword>
    <profile>%s</profile>
    <msg>attr %s, visibility limiters mean that the following atoms aren't
        accessible, resulting in non-modular x deps: %s</msg>
</check>""" % (self.__class__.__name__, self.category, self.package,
    self.version, self.keyword, self.profile, self.attr,
    escape(", ".join(self.failed)))
