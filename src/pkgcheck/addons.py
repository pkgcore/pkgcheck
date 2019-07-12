"""Addon functionality shared by multiple checkers."""

from collections import OrderedDict, defaultdict
from copy import copy
from functools import partial
from itertools import chain, filterfalse
import os
import pickle
import shlex
import subprocess

from pkgcore.ebuild.atom import MalformedAtom, atom as atom_cls
from pkgcore.repository import multiplex
from pkgcore.repository.util import SimpleTree
from snakeoil.cli.arghparse import StoreBool
from snakeoil.cli.exceptions import UserException
from snakeoil.containers import ProtectedSet
from snakeoil.demandload import demandload, demand_compile_regexp
from snakeoil.iterables import expandable_chain
from snakeoil.osutils import abspath, listdir_files, pjoin
from snakeoil.process.spawn import spawn_get_output
from snakeoil.sequences import iflatten_instance
from snakeoil.strings import pluralism as _pl

from . import base

demandload(
    'pkgcore.restrictions:packages,values',
    'pkgcore.ebuild:misc,domain,profiles,repo_objs',
    'pkgcore.log:logger',
)

# hacky ebuild path regexes for git log parsing, proper atom validation is handled later
demand_compile_regexp('ebuild_path_regex', r'^([^/]+)/([^/]+)/([^/]+)\.ebuild$')
demand_compile_regexp('ebuild_rename_regex', r'^([^/]+)/([^/]+)/{([^/]+)\.ebuild => ([^/]+)\.ebuild}$')


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


class QueryCacheAddon(base.Template):

    priority = 1

    @staticmethod
    def mangle_argparser(parser):
        group = parser.add_argument_group('query caching')
        group.add_argument(
            '--reset-caching-per', dest='query_caching_freq',
            choices=('version', 'package', 'category'), default='package',
            help='control how often the cache is cleared '
                 '(version, package or category)')

    @staticmethod
    def check_args(parser, namespace):
        namespace.query_caching_freq = {
            'version': base.versioned_feed,
            'package': base.package_feed,
            'category': base.repository_feed,
            }[namespace.query_caching_freq]

    def __init__(self, options):
        super().__init__(options)
        self.query_cache = {}
        # XXX this should be logging debug info
        self.feed_type = self.options.query_caching_freq

    def feed(self, item, reporter):
        # XXX as should this.
        self.query_cache.clear()


class profile_data(object):

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


class _ParseGitRepo(object):
    """Parse repository git logs."""

    def __init__(self, repo, commit):
        self.path = repo.location
        self.commit = commit
        self.pkg_map = self._process_git_repo()

    @property
    def _git_cmd(self):
        raise NotImplementedError

    def _parse_line(self, line):
        raise NotImplementedError

    def update(self, commit):
        self._process_git_repo(self._pkg_map, self.commit)
        self.commit = commit

    def _process_git_repo(self, pkg_map=None, commit=None):
        if pkg_map is None:
            pkg_map = {}

        cmd = shlex.split(self._git_cmd)
        if commit:
            cmd.append(f'{commit}..origin/HEAD')
        else:
            cmd.append('origin/HEAD')
        git_log = subprocess.Popen(cmd, stdout=subprocess.PIPE, cwd=self.path)

        line = git_log.stdout.readline().strip().decode()
        while line:
            if not line.startswith('commit '):
                raise RuntimeError(f'unknown git log output: {line!r}')
            commit = line[7:].strip()
            # author
            git_log.stdout.readline()
            # date
            line = git_log.stdout.readline().strip().decode()
            if not line.startswith('Date:'):
                raise RuntimeError(f'unknown git log output: {line!r}')
            date = line[5:].strip()

            while line and not line.startswith('commit '):
                line = git_log.stdout.readline().decode()
                atom = self._parse_line(line)
                if atom is not None:
                    pkg_map.setdefault(
                        atom.category, {}).setdefault(
                            atom.package, []).append((atom.fullver, date))

        return pkg_map


class GitRemovalRepo(_ParseGitRepo):
    """Parse repository git logs to determine ebuild removal dates."""

    cache_suffix = '-removal'

    @property
    def _git_cmd(self):
        return 'git log --diff-filter=D --summary --date=short --reverse'

    def _parse_line(self, line):
        if line.startswith(' delete mode '):
            path = line.rsplit(' ', 1)[1]
            match = ebuild_path_regex.match(path)
            if match:
                category = match.group(1)
                pkg = match.group(3)
                try:
                    return atom_cls(f'={category}/{pkg}')
                except MalformedAtom:
                    return None


class GitAddedRepo(_ParseGitRepo):
    """Parse repository git logs to determine ebuild added dates."""

    cache_suffix = '-added'

    @property
    def _git_cmd(self):
        return 'git log --diff-filter=AR --summary --date=short --reverse'

    def _parse_line(self, line):
        if line.startswith(' create mode '):
            path = line.rsplit(' ', 1)[1]
            match = ebuild_path_regex.match(path)
            if match:
                category = match.group(1)
                pkg = match.group(3)
                try:
                    return atom_cls(f'={category}/{pkg}')
                except MalformedAtom:
                    return None
        elif line.startswith(' rename '):
            path = line[8:].rsplit(' ', 1)[0]
            match = ebuild_rename_regex.match(path)
            if match:
                category = match.group(1)
                pkg = match.group(4)
                try:
                    return atom_cls(f'={category}/{pkg}')
                except MalformedAtom:
                    return None


class _DateRepo(object):
    """Repository supporting determining when a package version was removed."""

    def pkg_date(self, pkg):
        for version, date in self.cpv_dict[pkg.category][pkg.package]:
            if version == pkg.fullver:
                return date


class HistoricalRepo(SimpleTree, _DateRepo):
    """Repository encapsulating historical data."""

    def _get_versions(self, cp_key):
        return tuple(version for version, date in self.cpv_dict[cp_key[0]][cp_key[1]])


class HistoricalMultiplexRepo(multiplex.tree, _DateRepo):
    """Multiplex repo supporting historical queries across a repo and its masters."""


class GitAddon(base.Addon):

    @staticmethod
    def mangle_argparser(parser):
        group = parser.add_argument_group('git')
        group.add_argument(
            '--git-disable', action='store_true',
            help="disable checks that use git to parse repo logs")
        group.add_argument(
            '--git-cache', action='store_true',
            help="force git repo cache refresh",
            docs="""
                Parses a repo's git log and caches various historical information.
            """)

    def cached_repo(self, repo_cls, target_repo=None):
        repo = None
        if target_repo is None:
            target_repo = self.options.target_repo

        if not self.options.git_disable:
            # initialize repos cache dir
            cache_dir = pjoin(base.CACHE_DIR, 'repos')
            try:
                os.makedirs(cache_dir, exist_ok=True)
            except IOError as e:
                raise UserException(
                    f'failed creating profiles cache: {cache_dir!r}: {e.strerror}')

            git_repos = []
            for repo in target_repo.trees:
                ret, out = spawn_get_output(
                    ['git', 'rev-parse', 'origin/HEAD'], cwd=repo.location)
                if ret != 0:
                    break
                else:
                    commit = out[0].strip()

                    # handle duplicate repo IDs that are repo paths
                    cache_file = repo.repo_id.lstrip(os.sep).replace(os.sep, '-')
                    cache_file = pjoin(
                        cache_dir, f'{cache_file}{repo_cls.cache_suffix}.pickle')
                    git_repo = None
                    cache_repo = True
                    if not self.options.git_cache:
                        # try loading cached, historical repo data
                        try:
                            with open(cache_file, 'rb') as f:
                                git_repo = pickle.load(f)
                                if commit != git_repo.commit:
                                    git_repo.update(commit)
                                else:
                                    cache_repo = False
                        except (EOFError, FileNotFoundError, AttributeError) as e:
                            pass

                    if git_repo is None:
                        git_repo = repo_cls(repo, commit)

                    # only enable repo queries if history was found, e.g. a
                    # shallow clone with a depth of 1 won't have any history
                    if git_repo.pkg_map:
                        git_repos.append(HistoricalRepo(
                            git_repo.pkg_map, repo_id=f'{repo.repo_id}-history'))
                        # dump historical repo data
                        if cache_repo:
                            try:
                                with open(cache_file, 'wb+') as f:
                                    pickle.dump(git_repo, f)
                            except IOError as e:
                                msg = f'failed dumping git pkg repo: {cache_file!r}: {e.strerror}'
                                raise UserException(msg)
            else:
                if len(git_repos) > 1:
                    repo = HistoricalMultiplexRepo(*git_repos)
                elif len(git_repos) == 1:
                    repo = git_repos[0]
                    
        return repo


class ProfileAddon(base.Addon):

    required_addons = (ArchesAddon,)

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
            help="force profile cache refresh or disable cache usage",
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
                scanned.

                To specify disabled profiles prefix them with '-'. Note that
                when starting the argument list with a disabled profile an
                equals sign must be used, e.g. -p=-path/to/profile, otherwise
                the disabled profile argument is treated as an option.

                The special keywords of stable, dev, exp, and deprecated correspond to the
                lists of stable, development, experimental, and deprecated profiles,
                respectively. Therefore, to only scan all stable profiles
                pass the 'stable' argument to --profiles.
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
            selected_profiles = ((), ())

        if profiles_dir:
            profiles_obj = repo_objs.BundledProfiles(profiles_dir)
        else:
            profiles_obj = namespace.target_repo.config.profiles

        def norm_name(s):
            """Expand status keywords and format paths."""
            if s in ('dev', 'exp', 'stable', 'deprecated'):
                for x in profiles_obj.paths(s):
                    yield x
            else:
                yield '/'.join([_f for _f in s.split('/') if _f])

        disabled, enabled = selected_profiles
        disabled = set(disabled)
        enabled = set(enabled)

        # remove profiles that are both enabled and disabled
        toggled = enabled.intersection(disabled)
        enabled = enabled.difference(toggled)
        disabled = disabled.difference(toggled)
        ignore_deprecated = 'deprecated' not in enabled

        # expand status keywords, e.g. 'stable' -> set of stable profiles
        disabled = set(chain.from_iterable(map(norm_name, disabled)))
        enabled = set(chain.from_iterable(map(norm_name, enabled)))

        # If no profiles are enabled, then all that are defined in
        # profiles.desc are scanned except ones that are explicitly disabled.
        if not enabled:
            enabled = {
                profile for profile, status in
                chain.from_iterable(profiles_obj.arch_profiles.values())}

        profile_paths = enabled.difference(disabled)

        # only default to using cache when run without target args within a repo
        if namespace.profile_cache is None and namespace.default_target is None:
            namespace.profile_cache = False

        # initialize cache dir
        namespace.cache_file = pjoin(base.CACHE_DIR, 'profiles.pickle')
        if ((namespace.profile_cache is None or namespace.profile_cache) and
                not os.path.exists(base.CACHE_DIR)):
            try:
                os.makedirs(base.CACHE_DIR)
            except IOError as e:
                raise UserException(
                    f'failed creating profiles cache: {base.CACHE_DIR!r}: {e.strerror}')
        namespace.forced_cache = bool(namespace.profile_cache)

        # We hold onto the profiles as we're going, due to the fact that
        # profile nodes are weakly cached; hold onto all for this loop, avoids
        # a lot of reparsing at the expense of slightly more memory usage
        # temporarily.
        cached_profiles = []

        profile_status_map = dict(chain.from_iterable(
            profiles_obj.arch_profiles.values()))

        arch_profiles = defaultdict(list)
        for profile_path in profile_paths:
            try:
                p = profiles_obj.create_profile(profile_path)
            except profiles.ProfileError as e:
                # Only throw errors if the profile was selected by the user, bad
                # repo profiles will be caught during repo metadata scans.
                if namespace.profiles is not None:
                    parser.error(f'invalid profile: {e.path!r}: {e.error}')
                continue
            if ignore_deprecated and p.deprecated:
                continue
            cached_profiles.append(p)
            if p.arch is None:
                parser.error(f"profile {p.path!r} lacks arch settings, unable to use it")
            arch_profiles[p.arch].append((profile_path, p,
                profile_status_map.get(profile_path)))

        namespace.arch_profiles = arch_profiles

    def __init__(self, options, arches=None):
        super().__init__(options)

        # non-profile dirs found in the profiles directory, generally only in
        # the gentoo repo, but could be in overlays as well
        self.non_profile_dirs = {'desc', 'updates'}

        self.official_arches = options.target_repo.known_arches
        self.desired_arches = getattr(self.options, 'arches', None)
        if self.desired_arches is None or self.options.selected_arches is None:
            # copy it to be safe
            self.desired_arches = set(self.official_arches)

        self.global_insoluble = set()
        profile_filters = defaultdict(list)
        chunked_data_cache = {}
        cached_profile_filters = {}

        # try loading cached profile filters
        if options.profile_cache is None:
            try:
                with open(options.cache_file, 'rb') as f:
                    cached_profile_filters = pickle.load(f)
            except TypeError:
                # probably unmodifiable dict due to pkgcore issues, regenerate it
                os.remove(options.cache_file)
            except (EOFError, FileNotFoundError):
                pass

        for k in self.desired_arches:
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

            for profile_name, profile, profile_status in options.arch_profiles.get(k, []):
                vfilter = domain.generate_filter(profile.masks, profile.unmasks)

                cached_profile = cached_profile_filters.get(profile_name, None)
                if cached_profile:
                    immutable_flags = cached_profile[0]
                    stable_immutable_flags = cached_profile[1]
                    enabled_flags = cached_profile[2]
                    stable_enabled_flags = cached_profile[3]
                else:
                    # force cache updates unless explicitly disabled
                    if options.profile_cache is None:
                        options.profile_cache = True

                    immutable_flags = profile.masked_use.clone(unfreeze=True)
                    immutable_flags.add_bare_global((), default_masked_use)
                    immutable_flags.optimize(cache=chunked_data_cache)

                    stable_immutable_flags = profile.stable_masked_use.clone(unfreeze=True)
                    stable_immutable_flags.add_bare_global((), default_masked_use)
                    stable_immutable_flags.optimize(cache=chunked_data_cache)

                    enabled_flags = profile.forced_use.clone(unfreeze=True)
                    enabled_flags.add_bare_global((), (stable_key,))
                    enabled_flags.optimize(cache=chunked_data_cache)

                    stable_enabled_flags = profile.stable_forced_use.clone(unfreeze=True)
                    stable_enabled_flags.add_bare_global((), (stable_key,))
                    stable_enabled_flags.optimize(cache=chunked_data_cache)

                    if options.profile_cache:
                        # TODO: fix pickling ImmutableDict objects
                        # Grab a shallow copy of each profile mapping before it gets
                        # frozen to dump into the cache; otherwise loading the dumped dict
                        # fails due to its immutability.
                        cached_profile_filters[profile_name] = (
                            copy(immutable_flags), copy(stable_immutable_flags),
                            copy(enabled_flags), copy(stable_enabled_flags),
                        )

                # make profile data mappings immutable
                immutable_flags.freeze()
                stable_immutable_flags.freeze()
                enabled_flags.freeze()
                stable_enabled_flags.freeze()

                # used to interlink stable/unstable lookups so that if
                # unstable says it's not visible, stable doesn't try
                # if stable says something is visible, unstable doesn't try.
                stable_cache = set()
                unstable_insoluble = ProtectedSet(self.global_insoluble)

                # finalize enabled USE flags
                use = set()
                misc.incremental_expansion(use, profile.use, 'while expanding USE')

                # few notes.  for filter, ensure keywords is last, on the
                # offchance a non-metadata based restrict foregos having to
                # access the metadata.
                # note that the cache/insoluble are inversly paired;
                # stable cache is usable for unstable, but not vice versa.
                # unstable insoluble is usable for stable, but not vice versa

                profile_filters[stable_key].append(profile_data(
                    profile_name, stable_key,
                    profile.provides_repo,
                    packages.AndRestriction(vfilter, stable_r),
                    profile.iuse_effective,
                    use,
                    profile.pkg_use,
                    stable_immutable_flags, stable_enabled_flags,
                    stable_cache,
                    ProtectedSet(unstable_insoluble),
                    profile_status,
                    profile.deprecated is not None))

                profile_filters[unstable_key].append(profile_data(
                    profile_name, unstable_key,
                    profile.provides_repo,
                    packages.AndRestriction(vfilter, unstable_r),
                    profile.iuse_effective,
                    use,
                    profile.pkg_use,
                    immutable_flags, enabled_flags,
                    ProtectedSet(stable_cache),
                    unstable_insoluble,
                    profile_status,
                    profile.deprecated is not None))

        # dump cached profile filters
        if options.profile_cache:
            try:
                with open(options.cache_file, 'wb+') as f:
                    pickle.dump(cached_profile_filters, f)
            except IOError as e:
                msg = f'failed dumping profiles cache: {cache_file!r}: {e.strerror}'
                if not options.forced_cache:
                    logger.warn(msg)
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


class EvaluateDepSetAddon(base.Template):

    required_addons = (ProfileAddon,)
    feed_type = base.versioned_feed
    priority = 1

    def __init__(self, options, profiles):
        super().__init__(options)
        self.pkg_evaluate_depsets_cache = {}
        self.pkg_profiles_cache = {}
        self.profiles = profiles

    def feed(self, item, reporter):
        self.pkg_evaluate_depsets_cache.clear()
        self.pkg_profiles_cache.clear()

    def collapse_evaluate_depset(self, pkg, attr, depset):
        depset_profiles = self.pkg_evaluate_depsets_cache.get((pkg, attr))
        if depset_profiles is None:
            depset_profiles = self.identify_common_depsets(pkg, depset)
            self.pkg_evaluate_depsets_cache[(pkg, attr)] = depset_profiles
        return depset_profiles

    def identify_common_depsets(self, pkg, depset):
        profile_grps = self.pkg_profiles_cache.get(pkg, None)
        if profile_grps is None:
            profile_grps = self.profiles.identify_profiles(pkg)
            self.pkg_profiles_cache[pkg] = profile_grps

        # strip use dep defaults so known flags get identified correctly
        diuse = frozenset([x[:-3] if x[-1] == ')' else x
                          for x in depset.known_conditionals])
        collapsed = {}
        for profiles in profile_grps:
            immutable, enabled = profiles[0].identify_use(pkg, diuse)
            collapsed.setdefault((immutable, enabled), []).extend(profiles)

        return [(depset.evaluate_depset(k[1], tristate_filter=k[0]), v)
                for k, v in collapsed.items()]


class StableArchesAddon(base.Template):
    """Check relating to stable arches by default."""

    required_addons = (ArchesAddon,)

    def __init__(self, options, arches=None):
        super().__init__(options)
        # use known stable arches if arches aren't specified
        if options.selected_arches is None:
            stable_arches = set().union(*(repo.config.profiles.arches('stable')
                                   for repo in options.target_repo.trees))
        else:
            stable_arches = set(options.arches)

        options.stable_arches = stable_arches


class UnstatedIUSE(base.Error):
    """pkg is reliant on conditionals that aren't in IUSE"""
    __slots__ = ("category", "package", "version", "attr", "flags")

    threshold = base.versioned_feed

    def __init__(self, pkg, attr, flags):
        super().__init__()
        self._store_cpv(pkg)
        self.attr, self.flags = attr, tuple(flags)

    @property
    def short_desc(self):
        return "attr(%s) uses unstated flags: [ %s ]" % \
            (self.attr, ', '.join(self.flags))


class UseAddon(base.Addon):

    required_addons = (ProfileAddon,)
    known_results = (UnstatedIUSE,)

    def __init__(self, options, profiles, silence_warnings=False):
        super().__init__(options)

        # common profile elements
        c_implicit_iuse = set()
        if profiles:
            c_implicit_iuse = set.intersection(*(set(p.iuse_effective) for p in profiles))

        known_iuse = set()
        known_iuse_expand = set()

        for repo in options.target_repo.trees:
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
        self.unstated_iuse = frozenset(c_implicit_iuse)
        self.ignore = not (c_implicit_iuse or known_iuse or known_iuse_expand)
        if self.ignore and not silence_warnings:
            logger.warn('disabling use/iuse validity checks since no usable '
                        'use.desc, use.local.desc were found ')

    def allowed_iuse(self, pkg):
        return self.collapsed_iuse.pull_data(pkg).union(pkg.local_use)

    def get_filter(self, attr=None):
        if self.ignore:
            return self.fake_use_validate
        if attr is not None:
            return partial(self.use_validate, attr=attr)
        return self.use_validate

    @staticmethod
    def fake_use_validate(klasses, pkg, seq, reporter, attr=None):
        return iflatten_instance(seq, klasses)

    def use_validate(self, klasses, pkg, seq, reporter=None, attr=None):
        skip_filter = (packages.Conditional,) + klasses
        unstated = set()
        stated = pkg.iuse_stripped

        i = expandable_chain(iflatten_instance(seq, skip_filter))
        for node in i:
            if isinstance(node, packages.Conditional):
                # invert it; get only whats not in pkg.iuse
                unstated.update(filterfalse(stated.__contains__, node.restriction.vals))
                i.append(iflatten_instance(node.payload, skip_filter))
                continue
            elif attr == 'required_use':
                unstated.update(filterfalse(stated.__contains__, node.vals))
            yield node

        # implicit IUSE flags
        if reporter is not None and attr is not None:
            unstated.difference_update(self.unstated_iuse)
            if unstated:
                reporter.add_report(UnstatedIUSE(pkg, attr, sorted(unstated)))
