"""Profile specific support and addon."""

import os
import stat
from collections import defaultdict
from functools import partial
from itertools import chain

from pkgcore.ebuild import domain, misc
from pkgcore.ebuild import profiles as profiles_mod
from pkgcore.restrictions import packages, values
from snakeoil.cli import arghparse
from snakeoil.containers import ProtectedSet
from snakeoil.decorators import coroutine
from snakeoil.klass import jit_attr
from snakeoil.mappings import ImmutableDict
from snakeoil.osutils import pjoin

from .. import base
from ..base import PkgcheckUserException
from . import ArchesAddon, caches


class ProfileData:
    def __init__(
        self,
        repo,
        profile_name,
        key,
        provides,
        vfilter,
        iuse_effective,
        use,
        pkg_use,
        masked_use,
        forced_use,
        lookup_cache,
        insoluble,
        status,
        deprecated,
    ):
        self.repo = repo
        self.name = profile_name
        self.key = key
        self.provides_repo = provides
        self.provides_has_match = getattr(provides, "has_match", provides.match)
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
        immutable = enabled.union(filter(known_flags.__contains__, self.masked_use.pull_data(pkg)))
        if force_disabled := self.masked_use.pull_data(pkg):
            enabled = enabled.difference(force_disabled)
        return immutable, enabled


class ProfileNode(profiles_mod.ProfileNode):
    """Re-inherited to disable instance caching."""


class ProfilesArgs(arghparse.CommaSeparatedNegations):
    """Parse profiles args for the ProfileAddon."""

    @staticmethod
    def norm_name(repo, s):
        """Expand status keywords and format paths."""
        if s in ("dev", "exp", "stable", "deprecated"):
            yield from repo.profiles.get_profiles(status=s)
        elif s == "all":
            yield from repo.profiles
        else:
            try:
                yield repo.profiles[os.path.normpath(s)]
            except KeyError:
                raise ValueError(f"nonexistent profile: {s!r}")

    def __call__(self, parser, namespace, values, option_string=None):
        disabled, enabled = self.parse_values(values)
        namespace.ignore_deprecated_profiles = "deprecated" not in enabled

        # Expand status keywords, e.g. 'stable' -> set of stable profiles, and
        # translate selections into profile objs.
        norm_name = partial(self.norm_name, namespace.target_repo)
        try:
            disabled = set().union(*map(norm_name, disabled))
            enabled = set().union(*map(norm_name, enabled))
        except ValueError as e:
            parser.error(str(e))

        # If no profiles are enabled, then all that are defined in
        # profiles.desc are scanned except ones that are explicitly disabled.
        if not enabled:
            enabled = set(namespace.target_repo.profiles)

        profiles = enabled.difference(disabled)
        setattr(namespace, self.dest, profiles)
        namespace.profiles = profiles


class ProfileAddon(caches.CachedAddon):
    """Addon supporting ebuild repository profiles."""

    required_addons = (ArchesAddon,)

    # non-profile dirs found in the profiles directory, generally only in
    # the gentoo repo, but could be in overlays as well
    non_profile_dirs = frozenset(["desc", "updates"])

    # cache registry
    cache = caches.CacheData(type="profiles", file="profiles.pickle", version=2)

    @classmethod
    def mangle_argparser(cls, parser):
        group = parser.add_argument_group("profiles")
        group.add_argument(
            "-p",
            "--profiles",
            metavar="PROFILE",
            dest="selected_profiles",
            action=arghparse.Delayed,
            target=ProfilesArgs,
            priority=101,
            help="comma separated list of profiles to enable/disable",
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
            """,
        )
        parser.bind_delayed_default(1001, "profiles")(cls._default_profiles)

    @staticmethod
    def _default_profiles(namespace, attr):
        """Determine set of profiles to enable by default."""
        # Disable experimental profiles by default if no profiles are
        # selected and no keywords or arches have been explicitly selected
        # that require them to operate properly.
        target_repo = namespace.target_repo
        profiles = set(target_repo.profiles)
        if not getattr(namespace, "exp_profiles_required", False):
            profiles -= set(ProfilesArgs.norm_name(target_repo, "exp"))
        setattr(namespace, attr, profiles)

    def __init__(self, *args, arches_addon):
        super().__init__(*args)
        self.global_insoluble = set()
        self.profile_filters = {}
        self.profile_evaluate_dict = {}

        self.arch_profiles = defaultdict(list)
        self.target_repo = self.options.target_repo
        ignore_deprecated = getattr(self.options, "ignore_deprecated_profiles", True)

        for p in sorted(self.options.profiles):
            if p.deprecated and ignore_deprecated:
                continue
            try:
                profile = self.target_repo.profiles.create_profile(p, load_profile_base=False)
            except profiles_mod.ProfileError as e:
                # Only throw errors if the profile was selected by the user, bad
                # repo profiles will be caught during repo metadata scans.
                if self.options.selected_profiles is not None:
                    raise PkgcheckUserException(f"invalid profile: {e.path!r}: {e.error}")
                continue
            self.arch_profiles[p.arch].append((profile, p))

    @coroutine
    def _profile_files(self):
        """Given a profile object, return its file set and most recent mtime."""
        cache = {}
        while True:
            profile = yield
            profile_mtime = 0
            profile_files = []
            for node in profile.stack:
                mtime, files = cache.get(node.path, (0, []))
                if not mtime:
                    for f in os.listdir(node.path):
                        p = pjoin(node.path, f)
                        st_obj = os.lstat(p)
                        if stat.S_ISREG(st_obj.st_mode):
                            files.append(p)
                            if st_obj.st_mtime > mtime:
                                mtime = st_obj.st_mtime
                    cache[node.path] = (mtime, files)
                if mtime > profile_mtime:
                    profile_mtime = mtime
                profile_files.extend(files)
            yield profile_mtime, frozenset(profile_files)

    @jit_attr
    def profile_data(self):
        """Mapping of profile age and file sets used to check cache viability."""
        data = {}
        gen_profile_data = self._profile_files()
        for profile_obj, profile in chain.from_iterable(self.arch_profiles.values()):
            mtime, files = gen_profile_data.send(profile_obj)
            data[profile] = (mtime, files)
            next(gen_profile_data)
        return ImmutableDict(data)

    def update_cache(self, force=False):
        """Update related cache and push updates to disk."""
        cached_profiles = defaultdict(dict)
        official_arches = self.target_repo.known_arches

        with base.ProgressManager(verbosity=self.options.verbosity) as progress:
            for repo in self.target_repo.trees:
                cache_file = self.cache_file(repo)
                # add profiles-base -> repo mapping to ease storage procedure
                cached_profiles[repo.config.profiles_base]["repo"] = repo
                if not force:
                    cache = self.load_cache(cache_file, fallback={})
                    cached_profiles[repo.config.profiles_base].update(cache)

                chunked_data_cache = {}

                for arch in sorted(self.options.arches):
                    stable_key, unstable_key = arch, f"~{arch}"
                    stable_r = packages.PackageRestriction(
                        "keywords", values.ContainmentMatch2((stable_key,))
                    )
                    unstable_r = packages.PackageRestriction(
                        "keywords",
                        values.ContainmentMatch2(
                            (
                                stable_key,
                                unstable_key,
                            )
                        ),
                    )

                    default_masked_use = tuple(set(x for x in official_arches if x != stable_key))

                    # padding for progress output
                    padding = max(len(x) for x in self.options.arches)

                    for profile_obj, profile in self.arch_profiles.get(arch, []):
                        files = self.profile_data.get(profile)
                        try:
                            cached_profile = cached_profiles[repo.config.profiles_base][
                                profile.path
                            ]
                            if files != cached_profile["files"]:
                                # force refresh of outdated cache entry
                                raise KeyError

                            masks = cached_profile["masks"]
                            unmasks = cached_profile["unmasks"]
                            immutable_flags = cached_profile["immutable_flags"]
                            stable_immutable_flags = cached_profile["stable_immutable_flags"]
                            enabled_flags = cached_profile["enabled_flags"]
                            stable_enabled_flags = cached_profile["stable_enabled_flags"]
                            pkg_use = cached_profile["pkg_use"]
                            iuse_effective = cached_profile["iuse_effective"]
                            use = cached_profile["use"]
                            provides_repo = cached_profile["provides_repo"]
                        except KeyError:
                            try:
                                progress(
                                    f"{repo} -- updating profiles cache: {profile.arch:<{padding}}"
                                )

                                masks = profile_obj.masks
                                unmasks = profile_obj.unmasks

                                immutable_flags = profile_obj.masked_use.clone(unfreeze=True)
                                immutable_flags.add_bare_global((), default_masked_use)
                                immutable_flags.optimize(cache=chunked_data_cache)
                                immutable_flags.freeze()

                                stable_immutable_flags = profile_obj.stable_masked_use.clone(
                                    unfreeze=True
                                )
                                stable_immutable_flags.add_bare_global((), default_masked_use)
                                stable_immutable_flags.optimize(cache=chunked_data_cache)
                                stable_immutable_flags.freeze()

                                enabled_flags = profile_obj.forced_use.clone(unfreeze=True)
                                enabled_flags.add_bare_global((), (stable_key,))
                                enabled_flags.optimize(cache=chunked_data_cache)
                                enabled_flags.freeze()

                                stable_enabled_flags = profile_obj.stable_forced_use.clone(
                                    unfreeze=True
                                )
                                stable_enabled_flags.add_bare_global((), (stable_key,))
                                stable_enabled_flags.optimize(cache=chunked_data_cache)
                                stable_enabled_flags.freeze()

                                pkg_use = profile_obj.pkg_use
                                iuse_effective = profile_obj.iuse_effective
                                provides_repo = profile_obj.provides_repo

                                # finalize enabled USE flags
                                use = frozenset(
                                    misc.incremental_expansion(
                                        profile_obj.use, msg_prefix="while expanding USE"
                                    )
                                )
                            except profiles_mod.ProfileError:
                                # unsupported EAPI or other issue, profile checks will catch this
                                continue

                            cached_profiles[repo.config.profiles_base]["update"] = True
                            cached_profiles[repo.config.profiles_base][profile.path] = {
                                "files": files,
                                "masks": masks,
                                "unmasks": unmasks,
                                "immutable_flags": immutable_flags,
                                "stable_immutable_flags": stable_immutable_flags,
                                "enabled_flags": enabled_flags,
                                "stable_enabled_flags": stable_enabled_flags,
                                "pkg_use": pkg_use,
                                "iuse_effective": iuse_effective,
                                "use": use,
                                "provides_repo": provides_repo,
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
                        vfilter = domain.generate_filter(
                            self.target_repo.pkg_masks | masks, unmasks
                        )
                        self.profile_filters.setdefault(stable_key, []).append(
                            ProfileData(
                                repo.repo_id,
                                profile.path,
                                stable_key,
                                provides_repo,
                                packages.AndRestriction(vfilter, stable_r),
                                iuse_effective,
                                use,
                                pkg_use,
                                stable_immutable_flags,
                                stable_enabled_flags,
                                stable_cache,
                                ProtectedSet(unstable_insoluble),
                                profile.status,
                                profile.deprecated,
                            )
                        )

                        self.profile_filters.setdefault(unstable_key, []).append(
                            ProfileData(
                                repo.repo_id,
                                profile.path,
                                unstable_key,
                                provides_repo,
                                packages.AndRestriction(vfilter, unstable_r),
                                iuse_effective,
                                use,
                                pkg_use,
                                immutable_flags,
                                enabled_flags,
                                ProtectedSet(stable_cache),
                                unstable_insoluble,
                                profile.status,
                                profile.deprecated,
                            )
                        )

        # dump updated profile filters
        for k, v in cached_profiles.items():
            if v.pop("update", False):
                repo = v.pop("repo")
                cache_file = self.cache_file(repo)
                cache = caches.DictCache(cached_profiles[repo.config.profiles_base], self.cache)
                self.save_cache(cache, cache_file)

        for key, profile_list in self.profile_filters.items():
            similar = self.profile_evaluate_dict[key] = []
            for profile in profile_list:
                for existing in similar:
                    if (
                        existing[0].masked_use == profile.masked_use
                        and existing[0].forced_use == profile.forced_use
                    ):
                        existing.append(profile)
                        break
                else:
                    similar.append([profile])

    def identify_profiles(self, pkg):
        # yields groups of profiles; the 'groups' are grouped by the ability to share
        # the use processing across each of 'em.
        groups = []
        keywords = pkg.keywords
        unstable_keywords = (f"~{x}" for x in keywords if x[0] != "~")
        for key in chain(keywords, unstable_keywords):
            if profile_grps := self.profile_evaluate_dict.get(key):
                for profiles in profile_grps:
                    if group := [x for x in profiles if x.visible(pkg)]:
                        groups.append(group)
        return groups

    def __getitem__(self, key):
        """Return profiles matching a given keyword."""
        return self.profile_filters[key]

    def get(self, key, default=None):
        """Return profiles matching a given keyword with a fallback if none exist."""
        try:
            return self.profile_filters[key]
        except KeyError:
            return default

    def items(self):
        """Iterate over all keywords and profiles."""
        return self.profile_filters.items()

    def __iter__(self):
        """Iterate over all profile data objects."""
        return chain.from_iterable(self.profile_filters.values())

    def __len__(self):
        return len([x for x in self])
