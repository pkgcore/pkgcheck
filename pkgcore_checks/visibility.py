# Copyright: 2006-2011 Brian Harring <ferringb@gmail.com>
# License: BSD/GPL2

from pkgcore.ebuild.atom import atom
from snakeoil.iterables import caching_iter
from snakeoil.lists import stable_unique, iflatten_instance, iflatten_func
from snakeoil import klass

from pkgcore_checks import base, addons


class FakeConfigurable(object):
    configurable = True
    use = ()
    __slots__ = ('_raw_pkg', '_profile')

    def __init__(self, pkg, profile):
        object.__setattr__(self, '_raw_pkg', pkg)
        object.__setattr__(self, '_profile', profile)

    def request_enable(self, attr, *vals):
        if attr != 'use':
            return False

        set_vals = frozenset(vals)
        if self.eapi_obj.magic == '0':
            if not set_vals.issubset(self.iuse):
                return False
        else:
            if not set_vals.issubset(x.lstrip('-+') for x in self.iuse):
                # requested a flag that doesn't exist in iuse
                return False

        # if any of the flags are in masked_use, it's a no go.
        return set_vals.isdisjoint(
            self._profile.masked_use.pull_data(self._raw_pkg))

    def request_disable(self, attr, *vals):
        if attr != 'use':
            return False
        set_vals = frozenset(vals)
        if self.eapi_obj.magic == '0':
            if not set_vals.issubset(self.iuse):
                return False
        else:
            if set_vals.issubset(x.lstrip('-+') for x in self.iuse):
                # requested a flag that doesn't exist in iuse
                return False

        # if any of the flags are forced_use, it's a no go.
        return not set_vals.isdisjoint(
            self._profile.forced_use.pull_data(self._raw_pkg))

    def rollback(self, point=0):
        return True

    def changes_count(self):
        return 0

    __getattr__ = klass.GetAttrProxy("_raw_pkg")

    def __setattr__(self, attr, val):
        raise AttributeError(self, 'is immutable')



def _eapi2_flatten(val, atom_kls=atom,
    transitive_use_atom=atom._transitive_use_atom):
    return isinstance(val, atom_kls) and \
        not isinstance(val, transitive_use_atom)

def visit_atoms(pkg, stream):
    if not pkg.eapi_obj.options.transitive_use_atoms:
        return iflatten_instance(stream, atom)
    return iflatten_func(stream, _eapi2_flatten)

def strip_atom_use(inst):
    if not inst.use:
        return inst
    if '=*' == inst.op:
        s = '=%s*' % inst.cpvstr
    else:
        s = inst.op + inst.cpvstr
    if inst.blocks:
        s = '!' + s
        if not inst.blocks_temp_ignorable:
            s = '!' + s
    if inst.slot:
        s += ':%s' % inst.slot
    return atom(s)


class VisibleVcsPkg(base.Result):
    """pkg is vcs based, but visible"""

    __slots__ = ("category", "package", "version", "profile", "arch")

    threshold = base.versioned_feed

    def __init__(self, pkg, arch, profile):
        base.Result.__init__(self)
        self._store_cpv(pkg)
        self.arch = arch.lstrip("~")
        self.profile = profile

    @property
    def short_desc(self):
        return "VCS version visible for arch %s, profile %s" % (
            self.arch, self.profile)


class NonExistentDeps(base.Result):
    """No matches exist for a depset element"""

    __slots__ = ("category", "package", "version", "attr", "atoms")

    threshold = base.versioned_feed

    def __init__(self, pkg, attr, nonexistent_atoms):
        base.Result.__init__(self)
        self._store_cpv(pkg)
        self.attr = attr
        self.atoms = tuple(str(x) for x in nonexistent_atoms)

    @property
    def short_desc(self):
        return "depset %s: nonexistent atoms [ %s ]" % (
            self.attr, ', '.join(self.atoms))


class NonsolvableDeps(base.Result):
    """No potential solution for a depset attribute"""

    __slots__ = ("category", "package", "version", "attr", "profile",
        "keyword", "potentials")

    threshold = base.versioned_feed

    def __init__(self, pkg, attr, keyword, profile, horked):
        base.Result.__init__(self)
        self._store_cpv(pkg)
        self.attr = attr
        self.profile = profile
        self.keyword = keyword
        self.potentials = tuple(str(x) for x in stable_unique(horked))

    @property
    def short_desc(self):
        return "nonsolvable depset(%s) keyword(%s) profile (%s): " \
            "solutions: [ %s ]" % (self.attr, self.keyword, self.profile,
            ', '.join(self.potentials))


class VisibilityReport(base.Template):

    """Visibility dependency scans.
    Check that at least one solution is possible for a pkg, checking all
    profiles (defined by arch.list) visibility modifiers per stable/unstable
    keyword
    """

    feed_type = base.versioned_feed
    required_addons = (
        addons.ArchesAddon, addons.QueryCacheAddon, addons.ProfileAddon,
        addons.EvaluateDepSetAddon)
    known_results = (VisibleVcsPkg, NonExistentDeps, NonsolvableDeps)

    vcs_eclasses = frozenset(["subversion", "git", "cvs", "darcs", "tla", "bzr", "mercurial"])

    def __init__(self, options, arches, query_cache, profiles, depset_cache):
        base.Template.__init__(self, options)
        self.query_cache = query_cache.query_cache
        self.depset_cache = depset_cache
        self.profiles = profiles
        self.arches = frozenset(x.lstrip("~") for x in options.arches)

    def feed(self, pkg, reporter):
        # query_cache gets caching_iter partial repo searches shoved into it-
        # reason is simple, it's likely that versions of this pkg probably
        # use similar deps- so we're forcing those packages that were
        # accessed for atom matching to remain in memory.
        # end result is less going to disk

        fvcs = self.vcs_eclasses
        for eclass in pkg.inherited:
            if eclass in fvcs:
                # vcs ebuild that better not be visible
                self.check_visibility_vcs(pkg, reporter)
                break

        for attr, depset in (("depends", pkg.depends),
            ("rdepends", pkg.rdepends), ("post_rdepends", pkg.post_rdepends)):
            nonexistent = set()
            for orig_node in visit_atoms(pkg, depset):

                node = strip_atom_use(orig_node)
                if node not in self.query_cache:
                    if node in self.profiles.global_insoluble:
                        nonexistent.add(node)
                        # insert an empty tuple, so that tight loops further
                        # on don't have to use the slower get method
                        self.query_cache[node] = ()

                    else:
                        matches = caching_iter(
                            self.options.search_repo.itermatch(node))
                        if matches:
                            self.query_cache[node] = matches
                            if orig_node is not node:
                                self.query_cache[str(orig_node)] = matches
                        elif not node.blocks and not node.category == "virtual":
                            nonexistent.add(node)
                            self.query_cache[node] = ()
                            self.profiles.global_insoluble.add(node)
                elif not self.query_cache[node]:
                    nonexistent.add(node)

            if nonexistent:
                reporter.add_report(NonExistentDeps(pkg, attr, nonexistent))

        del nonexistent

        for attr, depset in (("depends", pkg.depends),
            ("rdepends", pkg.rdepends), ("post_rdepends", pkg.post_rdepends)):

            for edepset, profiles in self.depset_cache.collapse_evaluate_depset(
                pkg, attr, depset):

                self.process_depset(pkg, attr, edepset, profiles, reporter)

    def check_visibility_vcs(self, pkg, reporter):
        for key, profiles in self.profiles.profile_filters.iteritems():
            if key.startswith("~") or key.startswith("-"):
                continue
            for profile in profiles:
                if profile.visible(pkg):
                    reporter.add_report(VisibleVcsPkg(pkg,
                        profile.key, profile.name))

    def process_depset(self, pkg, attr, depset, profiles, reporter):
        get_cached_query = self.query_cache.get

        csolutions = []
        for required in depset.iter_cnf_solutions():
            for node in required:
                if node.blocks:
                    break
            else:
                csolutions.append(required)

        for profile in profiles:
            failures = set()
            # is it visible?  ie, is it masked?
            # if so, skip it.
            # long term, probably should do testing in the same respect we do
            # for other visibility tiers
            cache = profile.cache
            provided = profile.provides_has_match
            is_virtual = profile.virtuals_has_match
            insoluble = profile.insoluble
            visible = profile.visible
            for required in csolutions:
                # scan all of the quickies, the caches...
                for node in required:
                    if node in cache:
                        break
                    elif provided(node):
                        break
                    elif node.category == 'virtual' and is_virtual(node):
                        cache.add(node)
                        break
                else:
                    for node in required:
                        if node in insoluble:
                            pass

                        # get is required since there is an intermix between old style
                        # virtuals and new style- thus the cache priming doesn't get
                        # all of it.
                        src = get_cached_query(strip_atom_use(node), ())
                        if node.use:
                            src = (pkg for pkg in src if node.force_True(
                                FakeConfigurable(pkg, profile)))
                        if any(True for pkg in src if
                            visible(pkg)):
                            cache.add(node)
                            break
                        else:
                            insoluble.add(node)
                    else:
                        # no matches.  not great, should collect them all
                        failures.update(required)
            if failures:
                reporter.add_report(NonsolvableDeps(pkg, attr, profile.key,
                    profile.name, list(failures)))
