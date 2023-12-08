"""Various profile-related checks."""

from datetime import datetime
import os
from collections import defaultdict
from typing import Iterable

from pkgcore.ebuild import misc
from pkgcore.ebuild import profiles as profiles_mod
from pkgcore.ebuild.atom import atom as atom_cls
from pkgcore.ebuild.repo_objs import Profiles
from snakeoil.osutils import pjoin
from snakeoil.sequences import iflatten_instance
from snakeoil.strings import pluralism

from .. import addons, base, results, sources
from . import Check, RepoCheck


class OutdatedProfilePackage(results.ProfilesResult, results.Warning):
    """Profile files includes package entry that doesn't exist in the repo
    for a mentioned period of time.

    This is only reported if the version was removed more than 3 months ago,
    or all versions of this package were removed (i.e. last-rite).
    """

    def __init__(self, path, atom, age):
        super().__init__()
        self.path = path
        self.atom = str(atom)
        self.age = float(age)

    @property
    def desc(self):
        return f"{self.path!r}: outdated package entry: {self.atom!r}, last match removed {self.age} years ago"


class UnknownProfilePackage(results.ProfilesResult, results.Warning):
    """Profile files includes package entry that doesn't exist in the repo."""

    def __init__(self, path, atom):
        super().__init__()
        self.path = path
        self.atom = str(atom)

    @property
    def desc(self):
        return f"{self.path!r}: unknown package: {self.atom!r}"


class UnmatchedProfilePackageUnmask(results.ProfilesResult, results.Warning):
    """The profile's files include a package.unmask (or similar) entry which
    negates a non-existent mask, i.e. it undoes a mask which doesn't exist in
    the parent profile.

    No atoms matching this entry were found in the parent profile to unmask."""

    def __init__(self, path, atom):
        super().__init__()
        self.path = path
        self.atom = str(atom)

    @property
    def desc(self):
        return f"{self.path!r}: unmask of not masked package: {self.atom!r}"


class UnknownProfilePackageUse(results.ProfilesResult, results.Warning):
    """Profile files include entries with USE flags that aren't used on any matching packages."""

    def __init__(self, path, atom, flags):
        super().__init__()
        self.path = path
        self.atom = str(atom)
        self.flags = tuple(flags)

    @property
    def desc(self):
        s = pluralism(self.flags)
        flags = ", ".join(self.flags)
        atom = f"{self.atom}[{flags}]"
        return f"{self.path!r}: unknown package USE flag{s}: {atom!r}"


class UnknownProfileUse(results.ProfilesResult, results.Warning):
    """Profile files include USE flags that don't exist."""

    def __init__(self, path, flags):
        super().__init__()
        self.path = path
        self.flags = tuple(flags)

    @property
    def desc(self):
        s = pluralism(self.flags)
        flags = ", ".join(map(repr, self.flags))
        return f"{self.path!r}: unknown USE flag{s}: {flags}"


class UnknownProfilePackageKeywords(results.ProfilesResult, results.Warning):
    """Profile files include package keywords that don't exist."""

    def __init__(self, path, atom, keywords):
        super().__init__()
        self.path = path
        self.atom = str(atom)
        self.keywords = tuple(keywords)

    @property
    def desc(self):
        s = pluralism(self.keywords)
        keywords = ", ".join(map(repr, self.keywords))
        return f"{self.path!r}: unknown package keyword{s}: {self.atom}: {keywords}"


class UnknownProfileUseExpand(results.ProfilesResult, results.Warning):
    """Profile includes nonexistent USE_EXPAND group(s)."""

    def __init__(self, path: str, var: str, groups: Iterable[str]):
        super().__init__()
        self.path = path
        self.var = var
        self.groups = tuple(groups)

    @property
    def desc(self):
        s = pluralism(self.groups)
        groups = ", ".join(self.groups)
        return f"{self.path!r}: unknown USE_EXPAND group{s} in {self.var!r}: {groups}"


class UnknownProfileUseExpandValue(results.ProfilesResult, results.Warning):
    """Profile defines unknown default values for USE_EXPAND group."""

    def __init__(self, path: str, group: str, values: Iterable[str]):
        super().__init__()
        self.path = path
        self.group = group
        self.values = tuple(values)

    @property
    def desc(self):
        s = pluralism(self.values)
        values = ", ".join(self.values)
        return f"{self.path!r}: unknown value{s} for {self.group!r}: {values}"


class ProfileMissingImplicitExpandValues(results.ProfilesResult, results.Warning):
    """Profile is missing USE_EXPAND_VALUES for implicit USE_EXPAND group."""

    def __init__(self, path: str, groups: Iterable[str]):
        super().__init__()
        self.path = path
        self.groups = tuple(groups)

    @property
    def desc(self):
        s = pluralism(self.groups)
        groups = ", ".join(self.groups)
        return f"{self.path!r}: missing USE_EXPAND_VALUES for USE_EXPAND group{s}: {groups}"


class UnknownProfileArch(results.ProfilesResult, results.Warning):
    """Profile includes unknown ARCH."""

    def __init__(self, path: str, arch: str):
        super().__init__()
        self.path = path
        self.arch = arch

    @property
    def desc(self):
        return f"{self.path!r}: unknown ARCH {self.arch!r}"


class ProfileWarning(results.ProfilesResult, results.LogWarning):
    """Badly formatted data in various profile files."""


class ProfileError(results.ProfilesResult, results.LogError):
    """Erroneously formatted data in various profile files."""


# mapping of profile log levels to result classes
_logmap = (
    base.LogMap("pkgcore.log.logger.warning", ProfileWarning),
    base.LogMap("pkgcore.log.logger.error", ProfileError),
)


def verify_files(*files):
    """Decorator to register file verification methods."""

    class decorator:
        """Decorator with access to the class of a decorated function."""

        def __init__(self, func):
            self.func = func

        def __set_name__(self, owner, name):
            for file, attr in files:
                owner.known_files[file] = (attr, self.func)
            setattr(owner, name, self.func)

    return decorator


class ProfilesCheck(Check):
    """Scan repo profiles for unknown flags/packages."""

    _source = sources.ProfilesRepoSource
    required_addons = (addons.UseAddon, addons.KeywordsAddon, addons.git.GitAddon)
    known_results = frozenset(
        {
            OutdatedProfilePackage,
            UnknownProfilePackage,
            UnmatchedProfilePackageUnmask,
            UnknownProfilePackageUse,
            UnknownProfileUse,
            UnknownProfilePackageKeywords,
            UnknownProfileUseExpand,
            UnknownProfileUseExpandValue,
            ProfileMissingImplicitExpandValues,
            UnknownProfileArch,
            ProfileWarning,
            ProfileError,
        }
    )

    # mapping between known files and verification methods
    known_files = {}

    def __init__(
        self,
        *args,
        use_addon: addons.UseAddon,
        keywords_addon: addons.KeywordsAddon,
        git_addon: addons.git.GitAddon,
    ):
        super().__init__(*args)
        repo = self.options.target_repo
        self.keywords = keywords_addon
        self.search_repo = self.options.search_repo
        self.profiles_dir = repo.config.profiles_base
        self.today = datetime.today()
        self.existence_repo = git_addon.cached_repo(addons.git.GitRemovedRepo)
        self.use_expand_groups = {
            use.upper(): frozenset({val.removeprefix(f"{use}_") for val, _desc in vals})
            for use, vals in repo.config.use_expand_desc.items()
        }

        local_iuse = {use for _pkg, (use, _desc) in repo.config.use_local_desc}
        self.available_iuse = frozenset(
            local_iuse
            | use_addon.global_iuse
            | use_addon.global_iuse_expand
            | use_addon.global_iuse_implicit
        )

    def _report_unknown_atom(self, path, atom):
        if not isinstance(atom, atom_cls):
            atom = atom_cls(atom)
        if matches := self.existence_repo.match(atom):
            removal = max(x.time for x in matches)
            removal = datetime.fromtimestamp(removal)
            years = (self.today - removal).days / 365.2425
            # show years value if it's greater than 3 month, or if the package was removed
            if years > 0.25 or not self.search_repo.match(atom.unversioned_atom):
                return OutdatedProfilePackage(path, atom, round(years, 2))
        return UnknownProfilePackage(path, atom)

    @verify_files(("parent", "parents"), ("eapi", "eapi"))
    def _pull_attr(self, *args):
        """Verification only needs to pull the profile attr."""
        yield from ()

    @verify_files(("deprecated", "deprecated"))
    def _deprecated(self, filename, node, vals):
        # make sure replacement profile exists
        if vals is not None:
            replacement, _msg = vals
            try:
                addons.profiles.ProfileNode(pjoin(self.profiles_dir, replacement))
            except profiles_mod.ProfileError:
                yield ProfileError(
                    f"nonexistent replacement {replacement!r} "
                    f"for deprecated profile: {node.name!r}"
                )

    # non-spec files
    @verify_files(("package.keywords", "keywords"), ("package.accept_keywords", "accept_keywords"))
    def _pkg_keywords(self, filename, node, vals):
        for atom, keywords in vals:
            if invalid := sorted(set(keywords) - self.keywords.valid):
                yield UnknownProfilePackageKeywords(pjoin(node.name, filename), atom, invalid)

    @verify_files(
        ("use.force", "use_force"),
        ("use.stable.force", "use_stable_force"),
        ("use.mask", "use_mask"),
        ("use.stable.mask", "use_stable_mask"),
    )
    def _use(self, filename, node, vals):
        # TODO: give ChunkedDataDict some dict view methods
        d = vals.render_to_dict()
        for _, entries in d.items():
            for _, disabled, enabled in entries:
                if unknown_disabled := set(disabled) - self.available_iuse:
                    flags = ("-" + u for u in unknown_disabled)
                    yield UnknownProfileUse(pjoin(node.name, filename), sorted(flags))
                if unknown_enabled := set(enabled) - self.available_iuse:
                    yield UnknownProfileUse(pjoin(node.name, filename), sorted(unknown_enabled))

    @verify_files(
        ("packages", "packages"),
        ("package.unmask", "unmasks"),
        ("package.deprecated", "pkg_deprecated"),
    )
    def _pkg_atoms(self, filename, node, vals):
        for x in iflatten_instance(vals, atom_cls):
            if not isinstance(x, bool) and not self.search_repo.match(x):
                yield self._report_unknown_atom(pjoin(node.name, filename), x)

    @verify_files(
        ("package.mask", "masks"),
    )
    def _pkg_masks(self, filename, node, vals):
        all_masked = set().union(
            *(masked[1] for p in profiles_mod.ProfileStack(node.path).stack if (masked := p.masks))
        )

        unmasked, masked = vals
        for x in masked:
            if not self.search_repo.match(x):
                yield self._report_unknown_atom(pjoin(node.name, filename), x)
        for x in unmasked:
            if not self.search_repo.match(x):
                yield self._report_unknown_atom(pjoin(node.name, filename), x)
            elif x not in all_masked:
                yield UnmatchedProfilePackageUnmask(pjoin(node.name, filename), x)

    @verify_files(
        ("package.use", "pkg_use"),
        ("package.use.force", "pkg_use_force"),
        ("package.use.stable.force", "pkg_use_stable_force"),
        ("package.use.mask", "pkg_use_mask"),
        ("package.use.stable.mask", "pkg_use_stable_mask"),
    )
    def _pkg_use(self, filename, node, vals):
        # TODO: give ChunkedDataDict some dict view methods
        d = vals
        if isinstance(d, misc.ChunkedDataDict):
            d = vals.render_to_dict()

        for _pkg, entries in d.items():
            for a, disabled, enabled in entries:
                if pkgs := self.search_repo.match(a):
                    available = {u for pkg in pkgs for u in pkg.iuse_stripped}
                    if unknown_disabled := set(disabled) - available:
                        flags = ("-" + u for u in unknown_disabled)
                        yield UnknownProfilePackageUse(pjoin(node.name, filename), a, flags)
                    if unknown_enabled := set(enabled) - available:
                        yield UnknownProfilePackageUse(
                            pjoin(node.name, filename), a, unknown_enabled
                        )
                else:
                    yield self._report_unknown_atom(pjoin(node.name, filename), a)

    @verify_files(("make.defaults", "make_defaults"))
    def _make_defaults(self, filename: str, node: sources.ProfileNode, vals: dict[str, str]):
        if use_flags := {
            use.removeprefix("-")
            for use_group in ("USE", "IUSE_IMPLICIT")
            for use in vals.get(use_group, "").split()
        }:
            if unknown := use_flags - self.available_iuse:
                yield UnknownProfileUse(pjoin(node.name, filename), sorted(unknown))
        implicit_use_expands = set(vals.get("USE_EXPAND_IMPLICIT", "").split())
        for use_group in (
            "USE_EXPAND",
            "USE_EXPAND_HIDDEN",
            "USE_EXPAND_UNPREFIXED",
        ):
            values = {use.removeprefix("-") for use in vals.get(use_group, "").split()}
            if unknown := values - self.use_expand_groups.keys() - implicit_use_expands:
                yield UnknownProfileUseExpand(
                    pjoin(node.name, filename), use_group, sorted(unknown)
                )
        for key, val in vals.items():
            if key.startswith("USE_EXPAND_VALUES_"):
                use_group = key[18:]
                if use_group in implicit_use_expands:
                    continue
                elif allowed_values := self.use_expand_groups.get(use_group, None):
                    if unknown := set(val.split()) - allowed_values:
                        yield UnknownProfileUseExpandValue(
                            pjoin(node.name, filename), key, sorted(unknown)
                        )
                else:
                    yield UnknownProfileUseExpand(pjoin(node.name, filename), key, [use_group])
        for key in vals.keys() & self.use_expand_groups.keys():
            if unknown := set(vals.get(key, "").split()) - self.use_expand_groups[key]:
                yield UnknownProfileUseExpandValue(pjoin(node.name, filename), key, sorted(unknown))
        if missing_values := {
            use_group
            for use_group in implicit_use_expands
            if f"USE_EXPAND_VALUES_{use_group}" not in vals
        }:
            yield ProfileMissingImplicitExpandValues(
                pjoin(node.name, filename), sorted(missing_values)
            )
        if arch := vals.get("ARCH", None):
            if arch not in self.keywords.arches:
                yield UnknownProfileArch(pjoin(node.name, filename), arch)

    def feed(self, profile: sources.Profile):
        for f in profile.files.intersection(self.known_files):
            attr, func = self.known_files[f]
            with base.LogReports(*_logmap) as log_reports:
                data = getattr(profile.node, attr)
            yield from func(self, f, profile.node, data)
            yield from log_reports


class UnusedProfileDirs(results.ProfilesResult, results.Warning):
    """Unused profile directories detected."""

    def __init__(self, dirs):
        super().__init__()
        self.dirs = tuple(dirs)

    @property
    def desc(self):
        s = pluralism(self.dirs)
        dirs = ", ".join(map(repr, self.dirs))
        return f"unused profile dir{s}: {dirs}"


class ArchesWithoutProfiles(results.ProfilesResult, results.Warning):
    """Arches without corresponding profile listings."""

    def __init__(self, arches):
        super().__init__()
        self.arches = tuple(arches)

    @property
    def desc(self):
        es = pluralism(self.arches, plural="es")
        arches = ", ".join(self.arches)
        return f"arch{es} without profiles: {arches}"


class NonexistentProfilePath(results.ProfilesResult, results.Error):
    """Specified profile path in profiles.desc doesn't exist."""

    def __init__(self, path):
        super().__init__()
        self.path = path

    @property
    def desc(self):
        return f"nonexistent profile path: {self.path!r}"


class LaggingProfileEapi(results.ProfilesResult, results.Warning):
    """Profile has an EAPI that is older than one of its parents."""

    def __init__(self, profile, eapi, parent, parent_eapi):
        super().__init__()
        self.profile = profile
        self.eapi = eapi
        self.parent = parent
        self.parent_eapi = parent_eapi

    @property
    def desc(self):
        return (
            f"{self.profile!r} profile has EAPI {self.eapi}, "
            f"{self.parent!r} parent has EAPI {self.parent_eapi}"
        )


class _ProfileEapiResult(results.ProfilesResult):
    """Generic profile EAPI result."""

    _type = None

    def __init__(self, profile, eapi):
        super().__init__()
        self.profile = profile
        self.eapi = str(eapi)

    @property
    def desc(self):
        return f"{self.profile!r} profile is using {self._type} EAPI {self.eapi}"


class BannedProfileEapi(_ProfileEapiResult, results.Error):
    """Profile has an EAPI that is banned in the repository."""

    _type = "banned"


class DeprecatedProfileEapi(_ProfileEapiResult, results.Warning):
    """Profile has an EAPI that is deprecated in the repository."""

    _type = "deprecated"


class UnknownCategoryDirs(results.ProfilesResult, results.Warning):
    """Category directories that aren't listed in a repo's categories.

    Or the categories of the repo's masters as well.
    """

    def __init__(self, dirs):
        super().__init__()
        self.dirs = tuple(dirs)

    @property
    def desc(self):
        dirs = ", ".join(self.dirs)
        s = pluralism(self.dirs)
        return f"unknown category dir{s}: {dirs}"


class NonexistentCategories(results.ProfilesResult, results.Warning):
    """Category entries in profiles/categories that don't exist in the repo."""

    def __init__(self, categories):
        super().__init__()
        self.categories = tuple(categories)

    @property
    def desc(self):
        categories = ", ".join(self.categories)
        ies = pluralism(self.categories, singular="y", plural="ies")
        return f"nonexistent profiles/categories entr{ies}: {categories}"


class ArchesOutOfSync(results.ProfilesResult, results.Error):
    """``profiles/arches.desc`` is out of sync with ``arch.list``."""

    def __init__(self, arches):
        super().__init__()
        self.arches = tuple(arches)

    @property
    def desc(self):
        es = pluralism(self.arches, plural="es")
        arches = ", ".join(self.arches)
        return f"'profiles/arches.desc' is out of sync with 'arch.list', arch{es}: {arches}"


def dir_parents(path):
    """Yield all directory path parents excluding the root directory.

    Example:
    >>> list(dir_parents('/root/foo/bar/baz'))
    ['root/foo/bar', 'root/foo', 'root']
    """
    path = os.path.normpath(path.strip("/"))
    while path:
        yield path
        dirname, _basename = os.path.split(path)
        path = dirname.rstrip("/")


class RepoProfilesCheck(RepoCheck):
    """Scan repo for various profiles directory issues.

    Including unknown arches in profiles, arches without profiles, and unknown
    categories.
    """

    _source = (sources.EmptySource, (base.profiles_scope,))
    required_addons = (addons.profiles.ProfileAddon,)
    known_results = frozenset(
        {
            ArchesWithoutProfiles,
            UnusedProfileDirs,
            NonexistentProfilePath,
            UnknownCategoryDirs,
            NonexistentCategories,
            LaggingProfileEapi,
            ProfileError,
            ProfileWarning,
            BannedProfileEapi,
            DeprecatedProfileEapi,
            ArchesOutOfSync,
        }
    )

    # known profile status types for the gentoo repo
    known_profile_statuses = frozenset({"stable", "dev", "exp"})

    unknown_categories_whitelist = ("scripts",)

    def __init__(self, *args, profile_addon):
        super().__init__(*args)
        self.arches = self.options.target_repo.known_arches
        self.repo = self.options.target_repo
        self.profiles_dir = self.repo.config.profiles_base
        self.non_profile_dirs = profile_addon.non_profile_dirs

    def finish(self):
        if unknown_category_dirs := set(self.repo.category_dirs).difference(
            self.repo.categories, self.unknown_categories_whitelist
        ):
            yield UnknownCategoryDirs(sorted(unknown_category_dirs))
        if nonexistent_categories := set(self.repo.config.categories).difference(
            self.repo.category_dirs
        ):
            yield NonexistentCategories(sorted(nonexistent_categories))
        if arches_without_profiles := set(self.arches) - set(self.repo.profiles.arches()):
            yield ArchesWithoutProfiles(sorted(arches_without_profiles))

        root_profile_dirs = {"embedded"}
        available_profile_dirs = set()
        for root, _dirs, _files in os.walk(self.profiles_dir):
            if d := root[len(self.profiles_dir) :].lstrip("/"):
                available_profile_dirs.add(d)
        available_profile_dirs -= self.non_profile_dirs | root_profile_dirs

        # don't check for acceptable profile statuses on overlays
        if self.options.gentoo_repo:
            known_profile_statuses = self.known_profile_statuses
        else:
            known_profile_statuses = None

        # forcibly parse profiles.desc and convert log warnings/errors into reports
        with base.LogReports(*_logmap) as log_reports:
            profiles = Profiles.parse(
                self.profiles_dir,
                self.repo.repo_id,
                known_status=known_profile_statuses,
                known_arch=self.arches,
            )
        yield from log_reports

        banned_eapis = self.repo.config.profile_eapis_banned
        deprecated_eapis = self.repo.config.profile_eapis_deprecated

        seen_profile_dirs = set()
        banned_profile_eapi = set()
        deprecated_profile_eapi = set()
        lagging_profile_eapi = defaultdict(list)
        for p in profiles:
            try:
                profile = profiles_mod.ProfileStack(pjoin(self.profiles_dir, p.path))
            except profiles_mod.ProfileError:
                yield NonexistentProfilePath(p.path)
                continue
            for parent in profile.stack:
                seen_profile_dirs.update(dir_parents(parent.name))
                if profile.eapi is not parent.eapi and profile.eapi in parent.eapi.inherits:
                    lagging_profile_eapi[profile].append(parent)
                if str(parent.eapi) in banned_eapis:
                    banned_profile_eapi.add(parent)
                if str(parent.eapi) in deprecated_eapis:
                    deprecated_profile_eapi.add(parent)

        for profile, parents in lagging_profile_eapi.items():
            parent = parents[-1]
            yield LaggingProfileEapi(profile.name, str(profile.eapi), parent.name, str(parent.eapi))
        for profile in banned_profile_eapi:
            yield BannedProfileEapi(profile.name, profile.eapi)
        for profile in deprecated_profile_eapi:
            yield DeprecatedProfileEapi(profile.name, profile.eapi)

        if unused_profile_dirs := available_profile_dirs - seen_profile_dirs:
            yield UnusedProfileDirs(sorted(unused_profile_dirs))

        if arches_desc := frozenset().union(*self.repo.config.arches_desc.values()):
            if arches_mis_sync := self.repo.known_arches ^ arches_desc:
                yield ArchesOutOfSync(sorted(arches_mis_sync))
