"""Addon functionality shared by multiple checkers."""

import os
import pickle
import stat
from collections import UserDict, defaultdict
from functools import partial
from itertools import chain, filterfalse

from pkgcore.ebuild import domain, misc
from pkgcore.ebuild import profiles as profiles_mod
from pkgcore.ebuild import repo_objs
from pkgcore.restrictions import packages, values
from snakeoil import klass, mappings
from snakeoil.cli.arghparse import StoreBool
from snakeoil.cli.exceptions import UserException
from snakeoil.containers import ProtectedSet
from snakeoil.decorators import coroutine
from snakeoil.log import suppress_logging
from snakeoil.osutils import abspath, pjoin
from snakeoil.sequences import iflatten_instance
from snakeoil.strings import pluralism as _pl

from . import base, results
from .log import logger


class ArchesAddon(base.Addon):

    @staticmethod
    def check_args(parser, namespace):
        arches = namespace.selected_arches
        target_repo = getattr(namespace, "target_repo", None)
        if target_repo is not None:
            all_arches = target_repo.known_arches
        else:
            all_arches = set()

        if arches is None:
            arches = (set(), all_arches)
        disabled, enabled = arches
        if not enabled:
            # enable all non-prefix arches
            enabled = set(arch for arch in all_arches if '-' not in arch)

        arches = set(enabled).difference(set(disabled))
        if all_arches:
            unknown_arches = arches.difference(all_arches)
            if unknown_arches:
                parser.error('unknown arch%s: %s (valid arches: %s)' % (
                    _pl(unknown_arches, plural='es'),
                    ', '.join(unknown_arches),
                    ', '.join(sorted(all_arches))))

        namespace.arches = tuple(sorted(arches))

    @classmethod
    def mangle_argparser(cls, parser):
        group = parser.add_argument_group('arches')
        group.add_argument(
            '-a', '--arches', dest='selected_arches', metavar='ARCH',
            action='csv_negations',
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


class ProfileData:

    def __init__(self, profile_name, key, provides, vfilter,
                 iuse_effective, use, pkg_use, masked_use, forced_use, lookup_cache, insoluble,
                 status, deprecated):
        self.key = key
        self.name = profile_name
        self.provides_repo = provides
        self.provides_has_match = getattr(provides, 'has_match', provides.match)
        self.iuse_effective = iuse_effective
        self.use = use
        self.pkg_use = pkg_use
        self.masked_use = masked_use
        self.forced_use = forced_use
        self.cache = lookup_cache
        self.insoluble = insoluble
        self.visible = vfilter.match
        self.status = status
        self.deprecated = deprecated

    def identify_use(self, pkg, known_flags):
        # note we're trying to be *really* careful about not creating
        # pointless intermediate sets unless required
        # kindly don't change that in any modifications, it adds up.
        enabled = known_flags.intersection(self.forced_use.pull_data(pkg))
        immutable = enabled.union(
            filter(known_flags.__contains__, self.masked_use.pull_data(pkg)))
        force_disabled = self.masked_use.pull_data(pkg)
        if force_disabled:
            enabled = enabled.difference(force_disabled)
        return immutable, enabled


class _ProfilesCache(UserDict):
    """Class used to encapsulate cached profile data."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cache_version = ProfileAddon.cache_version


class ProfileAddon(base.Addon):

    required_addons = (ArchesAddon,)

    # non-profile dirs found in the profiles directory, generally only in
    # the gentoo repo, but could be in overlays as well
    non_profile_dirs = frozenset(['desc', 'updates'])

    # used to check profile cache compatibility
    cache_version = 1

    @staticmethod
    def mangle_argparser(parser):
        group = parser.add_argument_group('profiles')
        group.add_argument(
            "--profiles-base", dest='profiles_dir', default=None,
            help="path to base profiles directory",
            docs="""
                The path to the base profiles directory. This will override the
                default usage of profiles bundled in the target repository;
                primarily for testing.
            """)
        group.add_argument(
            '--profile-cache', action=StoreBool,
            help="forcibly enable/disable profile cache usage",
            docs="""
                Significantly decreases profile load time by caching and reusing
                the resulting filters rather than rebuilding them for each run.

                Caches are used by default. In order to forcibly refresh them,
                enable this option. Conversely, if caches are unwanted disable
                this instead.
            """)
        group.add_argument(
            '-p', '--profiles', metavar='PROFILE', action='csv_negations',
            dest='profiles',
            help='comma separated list of profiles to enable/disable',
            docs="""
                Comma separated list of profiles to enable and disable for
                scanning. Any profiles specified in this fashion will be the
                only profiles that get scanned, skipping any disabled profiles.
                In addition, if no profiles are explicitly enabled, all
                profiles defined in the target repo's profiles.desc file will be
                scanned except those marked as experimental (exp).

                To specify disabled profiles prefix them with ``-`` which
                removes the from the list of profiles to be considered. Note
                that when starting the argument list with a disabled profile an
                equals sign must be used, e.g.  ``-p=-path/to/profile``,
                otherwise the disabled profile argument is treated as an
                option.

                The special keywords of ``stable``, ``dev``, ``exp``, and
                ``deprecated`` correspond to the lists of stable, development,
                experimental, and deprecated profiles, respectively. Therefore,
                to only scan all stable profiles pass the ``stable`` argument
                to --profiles. Additionally the keyword ``all`` can be used to
                scan all defined profiles in the target repo.
            """)

    @staticmethod
    def check_args(parser, namespace):
        profiles_dir = getattr(namespace, "profiles_dir", None)
        if profiles_dir is not None:
            profiles_dir = abspath(profiles_dir)
            if not os.path.isdir(profiles_dir):
                parser.error(f"invalid profiles base: {profiles_dir!r}")

        selected_profiles = namespace.profiles
        if selected_profiles is None:
            # disable exp profiles by default if no profiles are selected
            selected_profiles = (('exp',), ())

        if profiles_dir:
            profiles_obj = repo_objs.Profiles(
                namespace.target_repo.config, profiles_base=profiles_dir)
        else:
            profiles_obj = namespace.target_repo.profiles

        def norm_name(s):
            """Expand status keywords and format paths."""
            if s in ('dev', 'exp', 'stable', 'deprecated'):
                yield from profiles_obj.get_profiles(status=s)
            elif s == 'all':
                yield from profiles_obj
            else:
                try:
                    yield profiles_obj[os.path.normpath(s)]
                except KeyError:
                    parser.error(f'nonexistent profile: {s!r}')

        disabled, enabled = selected_profiles
        disabled = set(disabled)
        enabled = set(enabled)

        # remove profiles that are both enabled and disabled
        toggled = enabled.intersection(disabled)
        enabled = enabled.difference(toggled)
        disabled = disabled.difference(toggled)
        ignore_deprecated = 'deprecated' not in enabled

        # Expand status keywords, e.g. 'stable' -> set of stable profiles, and
        # translate selections into profile objs.
        disabled = set(chain.from_iterable(map(norm_name, disabled)))
        enabled = set(chain.from_iterable(map(norm_name, enabled)))

        # If no profiles are enabled, then all that are defined in
        # profiles.desc are scanned except ones that are explicitly disabled.
        if not enabled:
            enabled = set(profiles_obj)

        profiles = enabled.difference(disabled)

        # disable profile cache usage for custom profiles directories
        if profiles_dir is not None:
            namespace.profile_cache = False
        namespace.forced_cache = bool(namespace.profile_cache)

        namespace.arch_profiles = defaultdict(list)
        for p in sorted(profiles):
            if ignore_deprecated and p.deprecated:
                continue

            try:
                profile = profiles_obj.create_profile(p)
            except profiles_mod.ProfileError as e:
                # Only throw errors if the profile was selected by the user, bad
                # repo profiles will be caught during repo metadata scans.
                if namespace.profiles is not None:
                    parser.error(f'invalid profile: {e.path!r}: {e.error}')
                continue

            with suppress_logging():
                if profile.arch is None:
                    # throw error if profiles have been explicitly selected, otherwise skip it
                    if namespace.profiles is not None:
                        parser.error(f'profile make.defaults lacks ARCH setting: {p.path!r}')
                    continue

            namespace.arch_profiles[profile.arch].append((profile, p))

    @coroutine
    def _profile_files(self):
        """Given a profile object, return its file set and most recent mtime."""
        cache = {}
        while True:
            profile = (yield)
            profile_mtime = 0
            profile_files = []
            for node in profile.stack:
                mtime, files = cache.get(node.path, (0, []))
                if not mtime:
                    for f in os.listdir(node.path):
                        p = pjoin(node.path, f)
                        files.append(p)
                        st_obj = os.lstat(p)
                        if stat.S_ISREG(st_obj.st_mode) and st_obj.st_mtime > mtime:
                            mtime = st_obj.st_mtime
                    cache[node.path] = (mtime, files)
                if mtime > profile_mtime:
                    profile_mtime = mtime
                profile_files.extend(files)
            yield profile_mtime, frozenset(profile_files)

    @klass.jit_attr
    def profile_data(self):
        """Mapping of profile age and file sets used to check cache viability."""
        data = {}
        if self.options.profile_cache is None or self.options.profile_cache:
            gen_profile_data = self._profile_files()
            for profile_obj, profile in chain.from_iterable(
                    self.options.arch_profiles.values()):
                mtime, files = gen_profile_data.send(profile_obj)
                data[profile] = (mtime, files)
                next(gen_profile_data)
            del gen_profile_data
        return mappings.ImmutableDict(data)

    def __init__(self, *args, arches_addon=None):
        super().__init__(*args)

        self.official_arches = self.options.target_repo.known_arches
        self.desired_arches = getattr(self.options, 'arches', None)
        if self.desired_arches is None or self.options.selected_arches is None:
            # copy it to be safe
            self.desired_arches = set(self.official_arches)

        self.global_insoluble = set()
        profile_filters = defaultdict(list)
        chunked_data_cache = {}
        cached_profiles = defaultdict(dict)

        if self.options.profile_cache or self.options.profile_cache is None:
            for repo in self.options.target_repo.trees:
                cache_dir = pjoin(base.CACHE_DIR, 'repos', repo.repo_id.lstrip(os.sep))
                cache_file = pjoin(cache_dir, 'profiles.pickle')
                # add profiles-base -> repo mapping to ease storage procedure
                cached_profiles[repo.config.profiles_base]['repo'] = repo
                # load cached profile filters by default
                if self.options.profile_cache is None:
                    try:
                        with open(cache_file, 'rb') as f:
                            cache = pickle.load(f)
                        if cache.cache_version == self.cache_version:
                            cached_profiles[repo.config.profiles_base].update(cache)
                        else:
                            logger.debug(
                                'forcing %s profile cache regen '
                                'due to outdated version', repo.repo_id)
                            os.remove(cache_file)
                    except FileNotFoundError as e:
                        pass
                    except (AttributeError, EOFError, ImportError, IndexError) as e:
                        logger.debug('forcing %s profile cache regen: %s', repo.repo_id, e)
                        os.remove(cache_file)

        for k in sorted(self.desired_arches):
            if k.lstrip("~") not in self.desired_arches:
                continue
            stable_key = k.lstrip("~")
            unstable_key = "~" + stable_key
            stable_r = packages.PackageRestriction(
                "keywords", values.ContainmentMatch2((stable_key,)))
            unstable_r = packages.PackageRestriction(
                "keywords", values.ContainmentMatch2((stable_key, unstable_key,)))

            default_masked_use = tuple(set(
                x for x in self.official_arches if x != stable_key))

            for profile_obj, profile in self.options.arch_profiles.get(k, []):
                files = self.profile_data.get(profile, None)
                try:
                    cached_profile = cached_profiles[profile.base][profile.path]
                    if files != cached_profile['files']:
                        # force refresh of outdated cache entry
                        raise KeyError

                    vfilter = cached_profile['vfilter']
                    immutable_flags = cached_profile['immutable_flags']
                    stable_immutable_flags = cached_profile['stable_immutable_flags']
                    enabled_flags = cached_profile['enabled_flags']
                    stable_enabled_flags = cached_profile['stable_enabled_flags']
                    pkg_use = cached_profile['pkg_use']
                    iuse_effective = cached_profile['iuse_effective']
                    use = cached_profile['use']
                    provides_repo = cached_profile['provides_repo']
                except KeyError:
                    logger.debug('profile regen: %s', profile.path)
                    with suppress_logging():
                        try:
                            vfilter = domain.generate_filter(profile_obj.masks, profile_obj.unmasks)

                            immutable_flags = profile_obj.masked_use.clone(unfreeze=True)
                            immutable_flags.add_bare_global((), default_masked_use)
                            immutable_flags.optimize(cache=chunked_data_cache)
                            immutable_flags.freeze()

                            stable_immutable_flags = profile_obj.stable_masked_use.clone(unfreeze=True)
                            stable_immutable_flags.add_bare_global((), default_masked_use)
                            stable_immutable_flags.optimize(cache=chunked_data_cache)
                            stable_immutable_flags.freeze()

                            enabled_flags = profile_obj.forced_use.clone(unfreeze=True)
                            enabled_flags.add_bare_global((), (stable_key,))
                            enabled_flags.optimize(cache=chunked_data_cache)
                            enabled_flags.freeze()

                            stable_enabled_flags = profile_obj.stable_forced_use.clone(unfreeze=True)
                            stable_enabled_flags.add_bare_global((), (stable_key,))
                            stable_enabled_flags.optimize(cache=chunked_data_cache)
                            stable_enabled_flags.freeze()

                            pkg_use = profile_obj.pkg_use
                            iuse_effective = profile_obj.iuse_effective
                            provides_repo = profile_obj.provides_repo

                            # finalize enabled USE flags
                            use = set()
                            misc.incremental_expansion(use, profile_obj.use, 'while expanding USE')
                            use = frozenset(use)
                        except profiles_mod.ProfileError:
                            # unsupported EAPI or other issue, profile checks will catch this
                            continue

                    if self.options.profile_cache or self.options.profile_cache is None:
                        cached_profiles[profile.base]['update'] = True
                        cached_profiles[profile.base][profile.path] = {
                            'files': files,
                            'vfilter': vfilter,
                            'immutable_flags': immutable_flags,
                            'stable_immutable_flags': stable_immutable_flags,
                            'enabled_flags': enabled_flags,
                            'stable_enabled_flags': stable_enabled_flags,
                            'pkg_use': pkg_use,
                            'iuse_effective': iuse_effective,
                            'use': use,
                            'provides_repo': provides_repo,
                        }

                # used to interlink stable/unstable lookups so that if
                # unstable says it's not visible, stable doesn't try
                # if stable says something is visible, unstable doesn't try.
                stable_cache = set()
                unstable_insoluble = ProtectedSet(self.global_insoluble)

                # few notes.  for filter, ensure keywords is last, on the
                # offchance a non-metadata based restrict foregos having to
                # access the metadata.
                # note that the cache/insoluble are inversly paired;
                # stable cache is usable for unstable, but not vice versa.
                # unstable insoluble is usable for stable, but not vice versa
                profile_filters[stable_key].append(ProfileData(
                    profile.path, stable_key,
                    provides_repo,
                    packages.AndRestriction(vfilter, stable_r),
                    iuse_effective,
                    use,
                    pkg_use,
                    stable_immutable_flags, stable_enabled_flags,
                    stable_cache,
                    ProtectedSet(unstable_insoluble),
                    profile.status,
                    profile.deprecated))

                profile_filters[unstable_key].append(ProfileData(
                    profile.path, unstable_key,
                    provides_repo,
                    packages.AndRestriction(vfilter, unstable_r),
                    iuse_effective,
                    use,
                    pkg_use,
                    immutable_flags, enabled_flags,
                    ProtectedSet(stable_cache),
                    unstable_insoluble,
                    profile.status,
                    profile.deprecated))

        # dump updated profile filters
        for k, v in cached_profiles.items():
            if v.pop('update', False):
                repo = v.pop('repo')
                cache_dir = pjoin(base.CACHE_DIR, 'repos', repo.repo_id.lstrip(os.sep))
                cache_file = pjoin(cache_dir, 'profiles.pickle')
                try:
                    os.makedirs(os.path.dirname(cache_file), exist_ok=True)
                    with open(cache_file, 'wb+') as f:
                        pickle.dump(_ProfilesCache(
                            cached_profiles[repo.config.profiles_base]), f)
                except IOError as e:
                    msg = (
                        f'failed dumping {repo.repo_id} profiles cache: '
                        f'{cache_file!r}: {e.strerror}')
                    if not self.options.forced_cache:
                        logger.warning(msg)
                    else:
                        raise UserException(msg)

        profile_evaluate_dict = {}
        for key, profile_list in profile_filters.items():
            similar = profile_evaluate_dict[key] = []
            for profile in profile_list:
                for existing in similar:
                    if (existing[0].masked_use == profile.masked_use and
                            existing[0].forced_use == profile.forced_use):
                        existing.append(profile)
                        break
                else:
                    similar.append([profile])

        self.profile_evaluate_dict = profile_evaluate_dict
        self.profile_filters = profile_filters

    def identify_profiles(self, pkg):
        # yields groups of profiles; the 'groups' are grouped by the ability to share
        # the use processing across each of 'em.
        l = []
        keywords = pkg.keywords
        unstable_keywords = tuple(f'~{x}' for x in keywords if x[0] != '~')
        for key in keywords + unstable_keywords:
            profile_grps = self.profile_evaluate_dict.get(key)
            if profile_grps is None:
                continue
            for profiles in profile_grps:
                l2 = [x for x in profiles if x.visible(pkg)]
                if not l2:
                    continue
                l.append(l2)
        return l

    def __getitem__(self, key):
        """Return profiles matching a given keyword."""
        return self.profile_filters[key]

    def get(self, key, default=None):
        """Return profiles matching a given keyword with a fallback if none exist."""
        try:
            return self.profile_filters[key]
        except KeyError:
            return default

    def __iter__(self):
        """Iterate over all profile data objects."""
        return chain.from_iterable(self.profile_filters.values())

    def __len__(self):
        return len([x for x in self])


class StableArchesAddon(base.Addon):
    """Check relating to stable arches by default."""

    required_addons = (ArchesAddon,)

    def __init__(self, *args, arches_addon=None):
        super().__init__(*args)
        # use known stable arches if arches aren't specified
        if self.options.selected_arches is None:
            stable_arches = set().union(*(
                repo.profiles.arches('stable')
                for repo in self.options.target_repo.trees))
        else:
            stable_arches = set(self.options.arches)

        self.options.stable_arches = stable_arches


class UnstatedIuse(results.VersionedResult, results.Error):
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
        msg.extend([f'unstated flag{_pl(self.flags)}', f'[ {flags} ]'])
        return ': '.join(msg)


class UseAddon(base.Addon):

    required_addons = (ProfileAddon,)

    def __init__(self, *args, profile_addon):
        super().__init__(*args)

        # common profile elements
        c_implicit_iuse = set()
        if profile_addon:
            c_implicit_iuse = set.intersection(*(set(p.iuse_effective) for p in profile_addon))

        known_iuse = set()
        known_iuse_expand = set()

        for repo in self.options.target_repo.trees:
            known_iuse.update(flag for matcher, (flag, desc) in repo.config.use_desc)
            known_iuse_expand.update(
                flag for flags in repo.config.use_expand_desc.values()
                for flag, desc in flags)

        self.collapsed_iuse = misc.non_incremental_collapsed_restrict_to_data(
            ((packages.AlwaysTrue, known_iuse),),
            ((packages.AlwaysTrue, known_iuse_expand),),
        )
        self.profiles = profile_addon
        self.global_iuse = frozenset(known_iuse)
        self.global_iuse_expand = frozenset(known_iuse_expand)
        self.global_iuse_implicit = frozenset(c_implicit_iuse)
        self.ignore = not (c_implicit_iuse or known_iuse or known_iuse_expand)
        if self.ignore:
            logger.debug(
                'disabling use/iuse validity checks since no usable '
                'use.desc and use.local.desc were found')

    def allowed_iuse(self, pkg):
        # metadata_xml checks catch xml issues, suppress warning/error logs here
        with suppress_logging():
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
                    profile_unstated = unstated_iuse - p.iuse_effective
                    if profile_unstated:
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
                yield UnstatedIuse(attr, unstated_iuse, pkg=pkg)

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

    def __init__(self, *args):
        super().__init__(*args)
        try:
            from .net import Session
            self.session = Session(
                concurrent=self.options.tasks, timeout=self.options.timeout)
        except ImportError as e:
            if e.name == 'requests':
                raise UserException('network checks require requests to be installed')
            raise


def init_addon(cls, options, addons_map=None):
    """Initialize a given addon."""
    if addons_map is None:
        addons_map = {}
    res = addons_map.get(cls)
    if res is not None:
        return res

    # initialize and inject all required addons for a given addon's inheritance
    # tree as kwargs
    required_addons = chain.from_iterable(
        x.required_addons for x in cls.__mro__ if issubclass(x, base.Addon))
    kwargs = {
        base.param_name(addon): init_addon(addon, options, addons_map)
        for addon in required_addons}
    res = addons_map[cls] = cls(options, **kwargs)
    return res
