from collections import defaultdict
from operator import attrgetter

from pkgcore.ebuild.atom import atom, transitive_use_atom
from snakeoil import klass
from snakeoil.iterables import caching_iter
from snakeoil.sequences import iflatten_func, iflatten_instance, stable_unique
from snakeoil.strings import pluralism

from .. import addons, feeds, results
from . import Check


class FakeConfigurable:
    "Package wrapper binding profile data."""

    configurable = True
    __slots__ = ('use', 'iuse', '_forced_use', '_masked_use', '_pkg_use', '_raw_pkg', '_profile')

    def __init__(self, pkg, profile):
        object.__setattr__(self, '_raw_pkg', pkg)
        object.__setattr__(self, '_profile', profile)

        object.__setattr__(
            self, '_forced_use', self._profile.forced_use.pull_data(self._raw_pkg))
        object.__setattr__(
            self, '_masked_use', self._profile.masked_use.pull_data(self._raw_pkg))
        object.__setattr__(
            self, '_pkg_use', self._profile.pkg_use.pull_data(self._raw_pkg))
        use_defaults = {x[1:] for x in pkg.iuse if x[0] == '+'}
        enabled_use = (use_defaults | profile.use | self._pkg_use | self._forced_use) - self._masked_use
        object.__setattr__(
            self, 'use', frozenset(enabled_use & (profile.iuse_effective | pkg.iuse_effective)))
        object.__setattr__(
            self, 'iuse', frozenset(profile.iuse_effective.union(pkg.iuse_stripped)))

    def request_enable(self, attr, *vals):
        if attr != 'use':
            return False

        set_vals = frozenset(vals)
        if not set_vals.issubset(self.iuse):
            # requested a flag that doesn't exist in iuse
            return False

        # if any of the flags are in masked_use, it's a no go.
        return set_vals.isdisjoint(self._masked_use)

    def request_disable(self, attr, *vals):
        if attr != 'use':
            return False

        set_vals = frozenset(vals)
        if not set_vals.issubset(self.iuse):
            # requested a flag that doesn't exist in iuse
            return False

        # if any of the flags are forced_use, it's a no go.
        return set_vals.isdisjoint(self._forced_use)

    def rollback(self, point=0):
        return True

    def changes_count(self):
        return 0

    def __str__(self):
        return str(self._raw_pkg)

    __getattr__ = klass.GetAttrProxy("_raw_pkg")

    def __setattr__(self, attr, val):
        raise AttributeError(self, 'is immutable')


class _BlockMemoryExhaustion(Exception):
    pass


# This is fast path code, hence the seperated implementations.
if getattr(atom, '_TRANSITIVE_USE_ATOM_BUG_IS_FIXED', False):
    def _eapi2_flatten(val):
        return isinstance(val, atom) and not isinstance(val, transitive_use_atom)
else:
    def _eapi2_flatten(val):
        if isinstance(val, transitive_use_atom):
            if len([x for x in val.use if x.endswith("?")]) > 16:
                raise _BlockMemoryExhaustion(val)
        return isinstance(val, atom) and not isinstance(val, transitive_use_atom)


def visit_atoms(pkg, stream):
    if not pkg.eapi.options.transitive_use_atoms:
        return iflatten_instance(stream, atom)
    return iflatten_func(stream, _eapi2_flatten)


class VisibleVcsPkg(results.VersionResult, results.Warning):
    """Package is VCS-based, but visible."""

    def __init__(self, arch, profile, num_profiles=None, **kwargs):
        super().__init__(**kwargs)
        self.arch = arch
        self.profile = profile
        self.num_profiles = num_profiles

    @property
    def desc(self):
        if self.num_profiles is not None and self.num_profiles > 1:
            num_profiles = f' ({self.num_profiles} total)'
        else:
            num_profiles = ''

        return (
            f'VCS version visible for KEYWORDS="{self.arch}", '
            f'profile {self.profile}{num_profiles}'
        )


class NonexistentDeps(results.VersionResult, results.Warning):
    """No matches exist for a package dependency."""

    def __init__(self, attr, nonexistent, **kwargs):
        super().__init__(**kwargs)
        self.attr = attr
        self.nonexistent = tuple(nonexistent)

    @property
    def desc(self):
        s = pluralism(self.nonexistent)
        nonexistent = ', '.join(self.nonexistent)
        return f'{self.attr}: nonexistent package{s}: {nonexistent}'


class UncheckableDep(results.VersionResult, results.Warning):
    """Given dependency cannot be checked due to the number of transitive use deps in it."""

    def __init__(self, attr, **kwargs):
        super().__init__(**kwargs)
        self.attr = attr

    @property
    def desc(self):
        return f"depset {self.attr}: could not be checked due to pkgcore limitation"


class NonsolvableDeps(results.VersionResult, results.AliasResult, results.Error):
    """No potential solution for a depset attribute."""

    def __init__(self, attr, keyword, profile, deps, profile_status,
                 profile_deprecated, num_profiles=None, **kwargs):
        super().__init__(**kwargs)
        self.attr = attr
        self.keyword = keyword
        self.profile = profile
        self.deps = tuple(deps)
        self.profile_status = profile_status
        self.profile_deprecated = profile_deprecated
        self.num_profiles = num_profiles

    @property
    def desc(self):
        profile_status = 'deprecated ' if self.profile_deprecated else ''
        profile_status += self.profile_status or 'custom'
        if self.num_profiles is not None and self.num_profiles > 1:
            num_profiles = f' ({self.num_profiles} total)'
        else:
            num_profiles = ''

        return (
            f"nonsolvable depset({self.attr}) keyword({self.keyword}) "
            f"{profile_status} profile ({self.profile}){num_profiles}: "
            f"solutions: [ {', '.join(self.deps)} ]"
        )


class NonsolvableDepsInStable(NonsolvableDeps):
    """No potential solution for dependency on stable profile."""


class NonsolvableDepsInDev(NonsolvableDeps):
    """No potential solution for dependency on dev profile."""


class NonsolvableDepsInExp(NonsolvableDeps):
    """No potential solution for dependency on exp profile."""

    # results require experimental profiles to be enabled
    _profile = 'exp'


class VisibilityCheck(feeds.EvaluateDepSet, feeds.QueryCache, Check):
    """Visibility dependency scans.

    Check that at least one solution is possible for a pkg, checking all
    profiles (defined by arch.list) visibility modifiers per stable/unstable
    keyword.
    """

    required_addons = (addons.profiles.ProfileAddon,)
    known_results = frozenset([
        VisibleVcsPkg, NonexistentDeps, UncheckableDep,
        NonsolvableDepsInStable, NonsolvableDepsInDev, NonsolvableDepsInExp,
    ])

    def __init__(self, *args, profile_addon):
        super().__init__(*args, profile_addon=profile_addon)
        self.profiles = profile_addon
        self.report_cls_map = {
            'stable': NonsolvableDepsInStable,
            'dev': NonsolvableDepsInDev,
            'exp': NonsolvableDepsInExp,
        }

    def feed(self, pkg):
        super().feed(pkg)

        # query_cache gets caching_iter partial repo searches shoved into it-
        # reason is simple, it's likely that versions of this pkg probably
        # use similar deps- so we're forcing those packages that were
        # accessed for atom matching to remain in memory.
        # end result is less going to disk

        if pkg.live:
            # vcs ebuild that better not be visible
            yield from self.check_visibility_vcs(pkg)

        suppressed_depsets = []
        for attr in (x.lower() for x in pkg.eapi.dep_keys):
            nonexistent = set()
            try:
                for orig_node in visit_atoms(pkg, getattr(pkg, attr)):
                    node = orig_node.no_usedeps
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
                            elif not node.blocks:
                                nonexistent.add(node)
                                self.query_cache[node] = ()
                                self.profiles.global_insoluble.add(node)
                    elif not self.query_cache[node]:
                        nonexistent.add(node)

            except _BlockMemoryExhaustion:
                yield UncheckableDep(attr, pkg=pkg)
                suppressed_depsets.append(attr)
            if nonexistent:
                nonexistent = map(str, sorted(nonexistent))
                yield NonexistentDeps(attr.upper(), nonexistent, pkg=pkg)

        for attr in (x.lower() for x in pkg.eapi.dep_keys):
            if attr in suppressed_depsets:
                continue
            depset = getattr(pkg, attr)
            profile_failures = defaultdict(lambda: defaultdict(set))
            for edepset, profiles in self.collapse_evaluate_depset(
                    pkg, attr, depset):
                for profile, failures in self.process_depset(
                        pkg, attr, depset, edepset, profiles):
                    failures = tuple(map(str, sorted(stable_unique(failures))))
                    profile_failures[failures][profile.status].add(profile)

            if profile_failures:
                if self.options.verbosity > 0:
                    # report all failures across all profiles in verbose mode
                    for failures, profiles in profile_failures.items():
                        for profile_status, cls in self.report_cls_map.items():
                            for profile in sorted(
                                    profiles.get(profile_status, ()),
                                    key=attrgetter('key', 'name')):
                                yield cls(
                                    attr, profile.key, profile.name, failures,
                                    profile_status, profile.deprecated, pkg=pkg)
                else:
                    # only report one failure per depset per profile type in regular mode
                    for failures, profiles in profile_failures.items():
                        for profile_status, cls in self.report_cls_map.items():
                            status_profiles = sorted(
                                profiles.get(profile_status, ()),
                                key=attrgetter('key', 'name'))
                            if status_profiles:
                                profile = status_profiles[0]
                                yield cls(
                                    attr, profile.key, profile.name,
                                    failures, profile_status,
                                    profile.deprecated, len(status_profiles), pkg=pkg)

    def check_visibility_vcs(self, pkg):
        visible = []
        for profile in self.profiles:
            if profile.visible(pkg):
                visible.append(profile)

        if visible:
            if self.options.verbosity > 0:
                # report all failures across all profiles in verbose mode
                for p in visible:
                    yield VisibleVcsPkg(p.key, p.name, pkg=pkg)
            else:
                p = visible[0]
                yield VisibleVcsPkg(p.key, p.name, len(visible), pkg=pkg)

    def process_depset(self, pkg, attr, depset, edepset, profiles):
        get_cached_query = self.query_cache.get

        csolutions = []
        for required in edepset.iter_cnf_solutions():
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
            insoluble = profile.insoluble
            visible = profile.visible
            for required in csolutions:
                # scan all of the quickies, the caches...
                for node in required:
                    if node in cache:
                        break
                    elif provided(node):
                        break
                else:
                    for node in required:
                        if node in insoluble:
                            pass

                        # get is required since there is an intermix between old style
                        # virtuals and new style- thus the cache priming doesn't get
                        # all of it.
                        src = get_cached_query(node.no_usedeps, ())
                        if node.use:
                            src = (FakeConfigurable(pkg, profile) for pkg in src)
                            src = (pkg for pkg in src if node.force_True(pkg))
                        if any(visible(pkg) for pkg in src):
                            cache.add(node)
                            break
                        else:
                            insoluble.add(node)
                    else:
                        # no matches. not great, should collect them all
                        failures.update(required)
            if failures:
                yield profile, failures
