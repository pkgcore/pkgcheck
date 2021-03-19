"""Addon functionality shared by multiple checkers."""

from collections import defaultdict
from functools import partial
from itertools import chain, filterfalse

from pkgcore.ebuild import misc
from pkgcore.ebuild import profiles as profiles_mod
from pkgcore.restrictions import packages
from snakeoil.cli import arghparse
from snakeoil.sequences import iflatten_instance
from snakeoil.strings import pluralism

from .. import base, results
from ..base import PkgcheckUserException
from ..log import logger
from . import caches


class ArchesArgs(arghparse.CommaSeparatedNegations):
    """Parse arches args for the ArchesAddon."""

    def __call__(self, parser, namespace, values, option_string=None):
        disabled, enabled = self.parse_values(values)
        all_arches = namespace.target_repo.known_arches

        if not enabled:
            # enable all non-prefix arches
            enabled = set(arch for arch in all_arches if '-' not in arch)

        arches = set(enabled).difference(disabled)
        if all_arches and (unknown_arches := arches.difference(all_arches)):
            es = pluralism(unknown_arches, plural='es')
            unknown = ', '.join(unknown_arches)
            valid = ', '.join(sorted(all_arches))
            parser.error(f'unknown arch{es}: {unknown} (valid arches: {valid})')

        # check if any selected arch only has experimental profiles
        for arch in arches:
            if all(p.status == 'exp' for p in namespace.target_repo.profiles if p.arch == arch):
                namespace.exp_profiles_required = True
                break

        arches = frozenset(arches)
        setattr(namespace, self.dest, arches)
        namespace.arches = arches


class ArchesAddon(base.Addon):
    """Addon supporting ebuild repository architectures."""

    @classmethod
    def mangle_argparser(cls, parser):
        group = parser.add_argument_group('arches')
        group.add_argument(
            '-a', '--arches', dest='selected_arches', metavar='ARCH', default=(),
            action=arghparse.Delayed, target=ArchesArgs, priority=100,
            help='comma separated list of arches to enable/disable',
            docs="""
                Comma separated list of arches to enable and disable.

                To specify disabled arches prefix them with '-'. Note that when
                starting the argument list with a disabled arch an equals sign
                must be used, e.g. -a=-arch, otherwise the disabled arch
                argument is treated as an option.

                By default all repo defined arches are used; however,
                stable-related checks (e.g. UnstableOnly) default to the set of
                arches having stable profiles in the target repo.
            """)
        parser.bind_delayed_default(1000, 'arches')(cls._default_arches)

    @staticmethod
    def _default_arches(namespace, attr):
        """Use all known arches by default."""
        setattr(namespace, attr, namespace.target_repo.known_arches)


class KeywordsAddon(base.Addon):
    """Addon supporting various keywords sets."""

    def __init__(self, *args):
        super().__init__(*args)
        special = {'-*'}
        self.arches = self.options.target_repo.known_arches
        unstable = {'~' + x for x in self.arches}
        disabled = {'-' + x for x in chain(self.arches, unstable)}
        self.valid = special | self.arches | unstable | disabled
        # Note: '*' and '~*' are portage-only, i.e. not in the spec, so they
        # don't belong in the main tree.
        self.portage = {'*', '~*'}


class StableArchesAddon(base.Addon):
    """Addon supporting stable architectures."""

    required_addons = (ArchesAddon,)

    @classmethod
    def mangle_argparser(cls, parser):
        parser.bind_delayed_default(1001, 'stable_arches')(cls._default_stable_arches)

    @staticmethod
    def _default_stable_arches(namespace, attr):
        """Determine set of stable arches to use."""
        target_repo = namespace.target_repo
        if not namespace.selected_arches:
            # use known stable arches (GLEP 72) if arches aren't specified
            stable_arches = target_repo.config.arches_desc['stable']
            # fallback to determining stable arches from profiles.desc if arches.desc doesn't exist
            if not stable_arches:
                stable_arches = set().union(*(
                    repo.profiles.arches('stable') for repo in target_repo.trees))
        else:
            stable_arches = namespace.arches

        setattr(namespace, attr, stable_arches)


class UnstatedIuse(results.VersionResult, results.Error):
    """Package is reliant on conditionals that aren't in IUSE."""

    def __init__(self, attr, flags, profile=None, num_profiles=None, **kwargs):
        super().__init__(**kwargs)
        self.attr = attr
        self.flags = tuple(flags)
        self.profile = profile
        self.num_profiles = num_profiles

    @property
    def desc(self):
        msg = [f'attr({self.attr})']
        if self.profile is not None:
            if self.num_profiles is not None:
                num_profiles = f' ({self.num_profiles} total)'
            else:
                num_profiles = ''
            msg.append(f'profile {self.profile!r}{num_profiles}')
        flags = ', '.join(self.flags)
        s = pluralism(self.flags)
        msg.extend([f'unstated flag{s}', f'[ {flags} ]'])
        return ': '.join(msg)


class UseAddon(base.Addon):
    """Addon supporting USE flag functionality."""

    def __init__(self, *args):
        super().__init__(*args)
        target_repo = self.options.target_repo

        self.profiles = []
        for p in target_repo.profiles:
            try:
                self.profiles.append(
                    target_repo.profiles.create_profile(p, load_profile_base=False))
            except profiles_mod.ProfileError:
                continue

        # TODO: Figure out if there is a more efficient method to determine a
        # repo's global implicit iuse while avoiding profiles cache usage. The
        # cache shouldn't be used in order to avoid cache regens when
        # performing scanning actions on specific profile files since the
        # current ProfilesCheck uses this addon.
        if self.profiles:
            c_implicit_iuse = set.intersection(*(set(p.iuse_effective) for p in self.profiles))
        else:
            c_implicit_iuse = set()

        known_iuse = set()
        known_iuse_expand = set()

        for repo in target_repo.trees:
            known_iuse.update(flag for matcher, (flag, desc) in repo.config.use_desc)
            known_iuse_expand.update(
                flag for flags in repo.config.use_expand_desc.values()
                for flag, desc in flags)

        self.collapsed_iuse = misc.non_incremental_collapsed_restrict_to_data(
            ((packages.AlwaysTrue, known_iuse),),
            ((packages.AlwaysTrue, known_iuse_expand),),
        )
        self.global_iuse = frozenset(known_iuse)
        self.global_iuse_expand = frozenset(known_iuse_expand)
        self.global_iuse_implicit = frozenset(c_implicit_iuse)
        self.ignore = not (c_implicit_iuse or known_iuse or known_iuse_expand)
        if self.ignore:
            logger.debug(
                'disabling use/iuse validity checks since no usable '
                'use.desc and use.local.desc were found')

    def allowed_iuse(self, pkg):
        return self.collapsed_iuse.pull_data(pkg).union(pkg.local_use)

    def get_filter(self, attr=None):
        if self.ignore:
            return self.fake_use_validate
        if attr is not None:
            return partial(self.use_validate, attr=attr)
        return self.use_validate

    @staticmethod
    def fake_use_validate(klasses, pkg, seq, attr=None):
        return {k: () for k in iflatten_instance(seq, klasses)}, ()

    def _flatten_restricts(self, nodes, skip_filter, stated, unstated, attr, restricts=None):
        for node in nodes:
            k = node
            v = restricts if restricts is not None else []
            if isinstance(node, packages.Conditional):
                # invert it; get only whats not in pkg.iuse
                unstated.update(filterfalse(stated.__contains__, node.restriction.vals))
                v.append(node.restriction)
                yield from self._flatten_restricts(
                    iflatten_instance(node.payload, skip_filter),
                    skip_filter, stated, unstated, attr, v)
                continue
            elif attr == 'required_use':
                unstated.update(filterfalse(stated.__contains__, node.vals))
            yield k, tuple(v)

    def _unstated_iuse(self, pkg, attr, unstated_iuse):
        """Determine if packages use unstated IUSE for a given attribute."""
        # determine profiles lacking USE flags
        if self.profiles:
            profiles_unstated = defaultdict(set)
            if attr is not None:
                for p in self.profiles:
                    if profile_unstated := unstated_iuse - p.iuse_effective:
                        profiles_unstated[tuple(sorted(profile_unstated))].add(p.name)

            for unstated, profiles in profiles_unstated.items():
                profiles = sorted(profiles)
                if self.options.verbosity > 0:
                    for p in profiles:
                        yield UnstatedIuse(attr, unstated, p, pkg=pkg)
                else:
                    num_profiles = len(profiles)
                    yield UnstatedIuse(attr, unstated, profiles[0], num_profiles, pkg=pkg)
        elif unstated_iuse:
            # Remove global defined implicit USE flags, note that standalone
            # repos without profiles will currently lack any implicit IUSE.
            unstated_iuse -= self.global_iuse_implicit
            if unstated_iuse:
                yield UnstatedIuse(attr, sorted(unstated_iuse), pkg=pkg)

    def use_validate(self, klasses, pkg, seq, attr=None):
        skip_filter = (packages.Conditional,) + klasses
        nodes = iflatten_instance(seq, skip_filter)
        unstated = set()
        vals = dict(self._flatten_restricts(
            nodes, skip_filter, stated=pkg.iuse_stripped, unstated=unstated, attr=attr))
        return vals, self._unstated_iuse(pkg, attr, unstated)


class NetAddon(base.Addon):
    """Addon supporting network functionality."""

    @classmethod
    def mangle_argparser(cls, parser):
        group = parser.add_argument_group('network')
        group.add_argument(
            '--timeout', type=float, default='5',
            help='timeout used for network checks')
        group.add_argument(
            '--user-agent', default='Wget/1.20.3 (linux-gnu)',
            help='custom user agent spoofing')

    @property
    def session(self):
        try:
            from .net import Session
            return Session(
                concurrent=self.options.tasks, timeout=self.options.timeout,
                user_agent=self.options.user_agent)
        except ImportError as e:
            if e.name == 'requests':
                raise PkgcheckUserException('network checks require requests to be installed')
            raise


def init_addon(cls, options, addons_map=None, **kwargs):
    """Initialize a given addon."""
    if addons_map is None:
        addons_map = {}

    try:
        addon = addons_map[cls]
    except KeyError:
        # initialize and inject all required addons for a given addon's inheritance
        # tree as kwargs
        required_addons = chain.from_iterable(
            x.required_addons for x in cls.__mro__ if issubclass(x, base.Addon))
        kwargs.update({
            base.param_name(addon): init_addon(addon, options, addons_map)
            for addon in required_addons})

        # verify the cache type is enabled
        if issubclass(cls, caches.CachedAddon) and not options.cache[cls.cache.type]:
            raise caches.CacheDisabled(cls.cache)

        addon = addons_map[cls] = cls(options, **kwargs)

        # force cache updates
        force_cache = getattr(options, 'force_cache', False)
        if isinstance(addon, caches.CachedAddon):
            addon.update_cache(force=force_cache)

    return addon
