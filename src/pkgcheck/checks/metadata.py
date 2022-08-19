import itertools
import os
import re
from collections import defaultdict
from datetime import datetime
from difflib import SequenceMatcher
from functools import partial
from operator import attrgetter

from pkgcore.ebuild import atom as atom_mod
from pkgcore.ebuild.atom import atom as atom_cls
from pkgcore.ebuild.eapi import get_eapi
from pkgcore.ebuild.misc import sort_keywords
from pkgcore.fetch import fetchable, unknown_mirror
from pkgcore.package.errors import MetadataException
from pkgcore.restrictions import boolean, packages, values
from snakeoil.mappings import ImmutableDict
from snakeoil.sequences import iflatten_instance
from snakeoil.strings import pluralism

from .. import addons, results, sources
from ..addons import UnstatedIuse
from ..base import LogMap, LogReports
from . import Check, GentooRepoCheck
from .visibility import FakeConfigurable


class _LicenseResult(results.VersionResult):
    """Generic license result."""

    license_type = None

    def __init__(self, licenses, **kwargs):
        super().__init__(**kwargs)
        self.licenses = tuple(licenses)

    @property
    def desc(self):
        s = pluralism(self.licenses)
        licenses = ', '.join(self.licenses)
        return f'{self.license_type} license{s}: {licenses}'


class UnknownLicense(_LicenseResult, results.Error):
    """License usage with no matching license file."""

    license_type = 'unknown'


class DeprecatedLicense(_LicenseResult, results.Warning):
    """Deprecated license usage."""

    license_type = 'deprecated'


class MissingLicense(results.VersionResult, results.Error):
    """Package has no LICENSE defined."""

    desc = 'no license defined'


class InvalidLicense(results.MetadataError, results.VersionResult):
    """Package's LICENSE is invalid."""

    attr = 'license'


class MissingLicenseRestricts(results.VersionResult, results.Warning):
    """Restrictive license used without matching RESTRICT."""

    def __init__(self, license_group, license, restrictions, **kwargs):
        super().__init__(**kwargs)
        self.license_group = license_group
        self.license = license
        self.restrictions = tuple(restrictions)

    @property
    def desc(self):
        restrictions = ' '.join(self.restrictions)
        return (
            f'{self.license_group} license {self.license!r} '
            f'requires RESTRICT="{restrictions}"'
        )


class UnnecessaryLicense(results.VersionResult, results.Warning):
    """LICENSE defined for package that is license-less."""

    @property
    def desc(self):
        return f"{self.category!r} packages shouldn't define LICENSE"


class LicenseCheck(Check):
    """LICENSE validity checks."""

    known_results = frozenset([
        InvalidLicense, MissingLicense, UnknownLicense, DeprecatedLicense,
        UnnecessaryLicense, UnstatedIuse, MissingLicenseRestricts,
    ])

    # categories for ebuilds that can lack LICENSE settings
    unlicensed_categories = frozenset(['virtual', 'acct-group', 'acct-user'])

    required_addons = (addons.UseAddon,)

    def __init__(self, *args, use_addon):
        super().__init__(*args)
        repo = self.options.target_repo
        self.iuse_filter = use_addon.get_filter('license')
        self.deprecated = repo.licenses.groups.get('DEPRECATED', frozenset())
        self.eula = repo.licenses.groups.get('EULA', frozenset())
        self.mirror_restricts = frozenset(['fetch', 'mirror'])

    def _required_licenses(self, license_group, nodes, restricts=None):
        """Determine required licenses from a given license group."""
        for node in nodes:
            v = restricts if restricts is not None else []
            if isinstance(node, str) and node not in license_group:
                continue
            elif isinstance(node, boolean.AndRestriction):
                yield from self._required_licenses(license_group, node, v)
                continue
            elif isinstance(node, boolean.OrRestriction):
                licenses = list(self._required_licenses(license_group, node, v))
                # skip conditionals that have another option
                if len(node) == len(licenses):
                    yield from licenses
                continue
            elif isinstance(node, packages.Conditional):
                v.append(node.restriction)
                yield from self._required_licenses(license_group, node.payload, v)
                continue
            yield node, tuple(v)

    def feed(self, pkg):
        # check for restrictive licenses with missing RESTRICT
        if self.eula is not None:
            for license, restrictions in self._required_licenses(self.eula, pkg.license):
                restricts = set().union(*(x.vals for x in restrictions if not x.negate))
                license_restrictions = pkg.restrict.evaluate_depset(restricts)
                missing_restricts = []
                if 'bindist' not in license_restrictions:
                    missing_restricts.append('bindist')
                if not self.mirror_restricts.intersection(license_restrictions):
                    if pkg.fetchables:
                        missing_restricts.append('mirror')
                if missing_restricts:
                    yield MissingLicenseRestricts(
                        'EULA', license, missing_restricts, pkg=pkg)

        # flatten license depset
        licenses, unstated = self.iuse_filter((str,), pkg, pkg.license)
        yield from unstated
        licenses = set(licenses)

        if not licenses:
            if pkg.category not in self.unlicensed_categories:
                yield MissingLicense(pkg=pkg)
        elif pkg.category in self.unlicensed_categories:
            yield UnnecessaryLicense(pkg=pkg)
        else:
            if unknown := licenses - set(pkg.repo.licenses):
                yield UnknownLicense(sorted(unknown), pkg=pkg)
            if deprecated := licenses & self.deprecated:
                yield DeprecatedLicense(sorted(deprecated), pkg=pkg)


class _UseFlagsResult(results.VersionResult):
    """Generic USE flags result."""

    flag_type = None

    def __init__(self, flags, **kwargs):
        super().__init__(**kwargs)
        self.flags = tuple(flags)

    @property
    def desc(self):
        s = pluralism(self.flags)
        flags = ', '.join(map(repr, sorted(self.flags)))
        return f'{self.flag_type} USE flag{s}: {flags}'


class InvalidUseFlags(_UseFlagsResult, results.Error):
    """Package IUSE contains invalid USE flags."""

    flag_type = 'invalid'


class UnknownUseFlags(_UseFlagsResult, results.Error):
    """Package IUSE contains unknown USE flags."""

    flag_type = 'unknown'


class BadDefaultUseFlags(_UseFlagsResult, results.Error):
    """Package IUSE contains bad default USE flags."""

    flag_type = 'bad default'


class IuseCheck(Check):
    """IUSE validity checks."""

    required_addons = (addons.UseAddon,)
    known_results = frozenset([InvalidUseFlags, UnknownUseFlags, BadDefaultUseFlags])
    use_expand_groups = ('cpu_flags',)

    def __init__(self, *args, use_addon):
        super().__init__(*args)
        self.iuse_handler = use_addon
        self.valid_use = atom_mod.valid_use_flag.match
        self.bad_defaults = tuple(['-'] + [f'+{x}_' for x in self.use_expand_groups])

    def feed(self, pkg):
        if invalid := sorted(x for x in pkg.iuse_stripped if not self.valid_use(x)):
            yield InvalidUseFlags(invalid, pkg=pkg)

        if pkg.eapi.options.iuse_defaults and (bad_defaults := sorted(
                x for x in pkg.iuse if x.startswith(self.bad_defaults) and len(x) > 1)):
            yield BadDefaultUseFlags(bad_defaults, pkg=pkg)

        if not self.iuse_handler.ignore:
            unknown = pkg.iuse_stripped.difference(self.iuse_handler.allowed_iuse(pkg))
            if unknown := unknown.difference(invalid):
                yield UnknownUseFlags(sorted(unknown), pkg=pkg)


class _EapiResult(results.VersionResult):
    """Generic EAPI result."""

    _type = None

    def __init__(self, eapi, **kwargs):
        super().__init__(**kwargs)
        self.eapi = str(eapi)

    @property
    def desc(self):
        return f"uses {self._type} EAPI {self.eapi}"


class DeprecatedEapi(_EapiResult, results.Warning):
    """Package's EAPI is deprecated according to repo metadata."""

    _type = 'deprecated'


class BannedEapi(_EapiResult, results.Error):
    """Package's EAPI is banned according to repo metadata."""

    _type = 'banned'


class StableKeywordsOnTestingEapi(results.VersionResult, results.Error):
    """Package has stable keywords on EAPI marked as testing-only."""

    def __init__(self, eapi, keywords, **kwargs):
        super().__init__(**kwargs)
        self.eapi = str(eapi)
        self.keywords = tuple(keywords)

    @property
    def desc(self):
        return f"stable keywords ({' '.join(self.keywords)}) on testing EAPI {self.eapi}"


class UnsupportedEclassEapi(results.VersionResult, results.Warning):
    """Ebuild inherits an eclass with outdated @SUPPORTED_EAPIS."""

    def __init__(self, eapi, eclass, **kwargs):
        super().__init__(**kwargs)
        self.eapi = eapi
        self.eclass = eclass

    @property
    def desc(self):
        return f"{self.eclass}.eclass doesn't support EAPI {self.eapi}"


class EapiCheck(Check):
    """Scan for packages with banned or deprecated EAPIs."""

    known_results = frozenset([DeprecatedEapi, BannedEapi, UnsupportedEclassEapi,
                               StableKeywordsOnTestingEapi])
    required_addons = (addons.eclass.EclassAddon,)

    def __init__(self, *args, eclass_addon):
        super().__init__(*args)
        self.eclass_cache = eclass_addon.eclasses

    def feed(self, pkg):
        eapi_str = str(pkg.eapi)
        if eapi_str in self.options.target_repo.config.eapis_banned:
            yield BannedEapi(pkg.eapi, pkg=pkg)
        elif eapi_str in self.options.target_repo.config.eapis_deprecated:
            yield DeprecatedEapi(pkg.eapi, pkg=pkg)

        if eapi_str in self.options.target_repo.config.eapis_testing:
            stable_keywords_gen = (k for k in pkg.keywords if not k.startswith(('~', '-')))
            if stable_keywords := sorted(stable_keywords_gen):
                yield StableKeywordsOnTestingEapi(pkg.eapi, stable_keywords, pkg=pkg)

        for eclass in pkg.inherit:
            if eclass_obj := self.eclass_cache.get(eclass):
                if eclass_obj.supported_eapis and eapi_str not in eclass_obj.supported_eapis:
                    yield UnsupportedEclassEapi(eapi_str, eclass, pkg=pkg)


class InvalidEapi(results.MetadataError, results.VersionResult):
    """Package's EAPI is invalid."""

    attr = 'eapi'


class InvalidSlot(results.MetadataError, results.VersionResult):
    """Package's SLOT is invalid."""

    attr = 'slot'


class SourcingError(results.MetadataError, results.VersionResult):
    """Failed sourcing ebuild."""

    attr = 'data'


class SourcingCheck(Check):
    """Scan for packages with sourcing errors or invalid, sourced metadata variables."""

    known_results = frozenset([SourcingError, InvalidEapi, InvalidSlot])
    # force this check to run first in its checkrunner
    priority = -100


class RequiredUseDefaults(results.VersionResult, results.Warning):
    """Default USE flag settings don't satisfy REQUIRED_USE.

    The REQUIRED_USE constraints specified in the ebuild are not satisfied
    by the default USE flags used in one or more profiles. This means that
    users on those profiles may be unable to install the package out of the box,
    without having to modify package.use.

    This warning is usually fixed via using IUSE defaults to enable one
    of the needed flags, modifying package.use in the most relevant profiles
    or modifying REQUIRED_USE.
    """

    def __init__(self, required_use, use=(), keyword=None,
                 profile=None, num_profiles=None, **kwargs):
        super().__init__(**kwargs)
        self.required_use = required_use
        self.use = tuple(use)
        self.keyword = keyword
        self.profile = profile
        self.num_profiles = num_profiles

    @property
    def desc(self):
        if not self.use:
            if self.num_profiles is not None and self.num_profiles > 1:
                num_profiles = f' ({self.num_profiles} total)'
            else:
                num_profiles = ''
            # collapsed version
            return (
                f'profile: {self.profile!r}{num_profiles} '
                f'failed REQUIRED_USE: {self.required_use}'
            )
        return (
            f'keyword: {self.keyword}, profile: {self.profile!r}, '
            f"default USE: [{', '.join(self.use)}] "
            f'-- failed REQUIRED_USE: {self.required_use}'
        )


class InvalidRequiredUse(results.MetadataError, results.VersionResult):
    """Package's REQUIRED_USE is invalid."""

    attr = 'required_use'


class RequiredUseCheck(Check):
    """REQUIRED_USE validity checks."""

    # only run the check for EAPI 4 and above
    _source = (sources.RestrictionRepoSource, (
        packages.PackageRestriction('eapi', values.GetAttrRestriction(
            'options.has_required_use', values.FunctionRestriction(bool))),))
    required_addons = (addons.UseAddon, addons.profiles.ProfileAddon)
    known_results = frozenset([InvalidRequiredUse, RequiredUseDefaults, UnstatedIuse])

    def __init__(self, *args, use_addon, profile_addon):
        super().__init__(*args)
        self.iuse_filter = use_addon.get_filter('required_use')
        self.profiles = profile_addon

    def feed(self, pkg):
        # check REQUIRED_USE for invalid nodes
        _nodes, unstated = self.iuse_filter((str,), pkg, pkg.required_use)
        yield from unstated

        # check both stable/unstable profiles for stable KEYWORDS and only
        # unstable profiles for unstable KEYWORDS
        keywords = []
        for keyword in pkg.sorted_keywords:
            if keyword[0] != '~':
                keywords.append(keyword)
            keywords.append('~' + keyword.lstrip('~'))

        # check USE defaults (pkg IUSE defaults + profile USE) against
        # REQUIRED_USE for all profiles matching a pkg's KEYWORDS
        failures = defaultdict(list)
        for keyword in keywords:
            for profile in sorted(self.profiles.get(keyword, ()), key=attrgetter('name')):
                # skip packages masked by the profile
                if profile.visible(pkg):
                    src = FakeConfigurable(pkg, profile)
                    for node in pkg.required_use.evaluate_depset(src.use):
                        if not node.match(src.use):
                            failures[node].append((src.use, profile.key, profile.name))

        if self.options.verbosity > 0:
            # report all failures with profile info in verbose mode
            for node, profile_info in failures.items():
                for use, keyword, profile in profile_info:
                    yield RequiredUseDefaults(
                        str(node), sorted(use), keyword, profile, pkg=pkg)
        else:
            # only report one failure per REQUIRED_USE node in regular mode
            for node, profile_info in failures.items():
                num_profiles = len(profile_info)
                _use, _keyword, profile = profile_info[0]
                yield RequiredUseDefaults(
                    str(node), profile=profile, num_profiles=num_profiles, pkg=pkg)


class UnusedLocalUse(results.PackageResult, results.Warning):
    """Unused local USE flag(s)."""

    def __init__(self, flags, **kwargs):
        super().__init__(**kwargs)
        self.flags = tuple(flags)

    @property
    def desc(self):
        s = pluralism(self.flags)
        flags = ', '.join(self.flags)
        return f'unused local USE flag{s}: [ {flags} ]'


class MatchingGlobalUse(results.PackageResult, results.Warning):
    """Local USE flag description matches a global USE flag."""

    def __init__(self, flag, **kwargs):
        super().__init__(**kwargs)
        self.flag = flag

    @property
    def desc(self):
        return f"local USE flag matches a global: {self.flag!r}"


class ProbableGlobalUse(results.PackageResult, results.Style):
    """Local USE flag description closely matches a global USE flag."""

    def __init__(self, flag, **kwargs):
        super().__init__(**kwargs)
        self.flag = flag

    @property
    def desc(self):
        return f"local USE flag closely matches a global: {self.flag!r}"


class ProbableUseExpand(results.PackageResult, results.Warning):
    """Local USE flag that isn't overridden matches a USE_EXPAND group.

    The local USE flag starts with a prefix reserved to USE_EXPAND group,
    yet it is not a globally defined member of this group. According
    to the standing policy [#]_, all possible values for each USE_EXPAND
    must be defined and documented globally.

    This warning can be fixed via moving the local flag description
    into appropriate profiles/desc file.

    .. [#] https://devmanual.gentoo.org/general-concepts/use-flags/
    """

    def __init__(self, flag, group, **kwargs):
        super().__init__(**kwargs)
        self.flag = flag
        self.group = group

    @property
    def desc(self):
        return f"USE_EXPAND group {self.group!r} matches local USE flag: {self.flag!r}"


class UnderscoreInUseFlag(results.PackageResult, results.Style):
    """USE flag uses underscore that is reserved for USE_EXPAND.

    The USE flag name uses underscore. However, according to PMS
    underscores are reserved for USE_EXPAND flags [#]_. The recommended
    replacement is hyphen ('-').

    .. [#] https://projects.gentoo.org/pms/7/pms.html#x1-200003.1.4
    """

    def __init__(self, flag, **kwargs):
        super().__init__(**kwargs)
        self.flag = flag

    @property
    def desc(self):
        return f"USE flag {self.flag!r} uses reserved underscore character"


class MissingLocalUseDesc(results.PackageResult, results.Warning):
    """Local USE flag(s) missing descriptions."""

    def __init__(self, flags, **kwargs):
        super().__init__(**kwargs)
        self.flags = tuple(flags)

    @property
    def desc(self):
        s = pluralism(self.flags)
        flags = ', '.join(self.flags)
        return f'local USE flag{s} missing description{s}: [ {flags} ]'


class LocalUseCheck(Check):
    """Check local USE flags in metadata.xml for various issues."""

    _source = sources.PackageRepoSource
    required_addons = (addons.UseAddon,)
    known_results = frozenset([
        UnusedLocalUse, MatchingGlobalUse, ProbableGlobalUse,
        ProbableUseExpand, UnderscoreInUseFlag, UnstatedIuse,
        MissingLocalUseDesc,
    ])

    def __init__(self, *args, use_addon):
        super().__init__(*args)
        repo_config = self.options.target_repo.config
        self.iuse_handler = use_addon
        self.global_use = {
            flag: desc for matcher, (flag, desc) in repo_config.use_desc}

        self.use_expand = dict()
        for group in repo_config.use_expand_desc.keys():
            self.use_expand[group] = {
                flag for flag, desc in repo_config.use_expand_desc[group]}

    def feed(self, pkgs):
        pkg = pkgs[0]
        local_use = pkg.local_use
        missing_desc = []

        for flag, desc in local_use.items():
            if not desc:
                missing_desc.append(flag)

            if flag in self.global_use:
                ratio = SequenceMatcher(None, desc, self.global_use[flag]).ratio()
                if ratio == 1.0:
                    yield MatchingGlobalUse(flag, pkg=pkg)
                elif ratio >= 0.75:
                    yield ProbableGlobalUse(flag, pkg=pkg)
            elif '_' in flag:
                for group, flags in self.use_expand.items():
                    if flag.startswith(f'{group}_'):
                        if flag not in flags:
                            yield ProbableUseExpand(flag, group.upper(), pkg=pkg)
                        break
                else:
                    yield UnderscoreInUseFlag(flag, pkg=pkg)

        unused = set(local_use)
        for pkg in pkgs:
            unused.difference_update(pkg.iuse_stripped)
        if unused:
            yield UnusedLocalUse(sorted(unused), pkg=pkg)
        if missing_desc:
            yield MissingLocalUseDesc(sorted(missing_desc), pkg=pkg)


class UseFlagWithoutDeps(results.VersionResult, results.Warning):
    """Special USE flag with little utility and without effect on dependencies.

    Various USE flags, such as "ipv6", should be always turned on or off, and
    their existence is questionable, in cases were it doesn't introduce new
    dependencies. Other USE flags, such as "bash-completion", without any new
    dependencies, are probable violators of small files QA policy [#]_.

    In cases where this USE flag is appropriate, you can silence this warning
    by adding a description to this USE flag in ``metadata.xml`` file and thus
    making it a local USE flag instead of global one.

    .. [#] https://projects.gentoo.org/qa/policy-guide/installed-files.html#pg0301
    """

    def __init__(self, flags, **kwargs):
        super().__init__(**kwargs)
        self.flags = tuple(flags)

    @property
    def desc(self):
        s = pluralism(self.flags)
        flags = ', '.join(self.flags)
        return f'special small-files USE flag{s} without effect on dependencies: [ {flags} ]'


class UseFlagsWithoutEffectsCheck(GentooRepoCheck):
    """Check for USE flags without effects."""

    known_results = frozenset({
        UseFlagWithoutDeps,
    })

    warn_use_small_files = frozenset({
        'ipv6', 'logrotate', 'unicode',
        'bash-completion', 'fish-completion', 'zsh-completion', 'vim-syntax',
        # TODO: enable those one day
        # 'systemd',
    })

    def feed(self, pkg):
        used_flags = set(pkg.local_use)
        for attr in pkg.eapi.dep_keys:
            deps = getattr(pkg, attr.lower())

            use_values = set()
            use_values.update(itertools.chain.from_iterable(
                atom.use or ()
                for atom in iflatten_instance(deps, atom_cls)
            ))
            use_values.update(itertools.chain.from_iterable(
                atom.restriction.vals
                for atom in iflatten_instance(deps, packages.Conditional)
                if isinstance(atom, packages.Conditional) and atom.attr == 'use'
            ))
            for check_use in self.warn_use_small_files:
                if any(check_use in use for use in use_values):
                    used_flags.add(check_use)

        flags = self.warn_use_small_files.intersection(pkg.iuse_stripped).difference(used_flags)
        if flags:
            yield UseFlagWithoutDeps(flags, pkg=pkg)

class MissingSlotDep(results.VersionResult, results.Warning):
    """Missing slot value in dependencies.

    The package dependency does not specify a slot but the target package
    has multiple slots. The behavior for satisfying this kind of dependency
    is not strictly defined, and may result in either any or the newest package
    slot being accepted.

    Please verify whether the package works with all the dependency slots.
    If only one slot is actually acceptable, specify it explicitly. If multiple
    slots are acceptable, please use either ``:=`` or explicit ``:*`` slot operator.
    The operators are described in detail in the devmanual [#]_.

    .. [#] https://devmanual.gentoo.org/general-concepts/dependencies/#slot-dependencies
    """

    def __init__(self, dep, dep_slots, **kwargs):
        super().__init__(**kwargs)
        self.dep = dep
        self.dep_slots = tuple(dep_slots)

    @property
    def desc(self):
        return (
            f"{self.dep!r} matches more than one slot: "
            f"[ {', '.join(self.dep_slots)} ]")


class MissingSlotDepCheck(Check):
    """Check for missing slot dependencies."""

    # only run the check for EAPI 5 and above
    _source = (sources.RestrictionRepoSource, (
        packages.PackageRestriction('eapi', values.GetAttrRestriction(
            'options.sub_slotting', values.FunctionRestriction(bool))),))
    required_addons = (addons.UseAddon,)
    known_results = frozenset([MissingSlotDep])

    def __init__(self, *args, use_addon):
        super().__init__(*args)
        self.iuse_filter = use_addon.get_filter()

    def feed(self, pkg):
        rdepend, _ = self.iuse_filter((atom_cls,), pkg, pkg.rdepend)
        depend, _ = self.iuse_filter((atom_cls,), pkg, pkg.depend)

        # skip deps that are blockers or have explicit slots/slot operators
        for dep in (x for x in set(rdepend).intersection(depend) if not
                    (x.blocks or x.slot is not None or x.slot_operator is not None)):
            dep_slots = {x.slot for x in pkg.repo.itermatch(dep.no_usedeps)}
            if len(dep_slots) > 1:
                yield MissingSlotDep(str(dep), sorted(dep_slots), pkg=pkg)


class MissingPackageRevision(results.VersionResult, results.Warning):
    """Missing package revision in =cat/pkg dependencies.

    The dependency string uses the ``=`` operator without specifying a revision.
    This means that only ``-r0`` of the dependency will be matched, and newer
    revisions of the same ebuild will not be accepted.

    If any revision of the package is acceptable, the ``~`` operator should be
    used instead of ``=``. If only the initial revision of the dependency is
    allowed, ``-r0`` should be appended in order to make the intent explicit.
    """

    def __init__(self, dep, atom, **kwargs):
        super().__init__(**kwargs)
        self.dep = dep.upper()
        self.atom = atom

    @property
    def desc(self):
        return f'"=" operator used without package revision: {self.dep}="{self.atom}"'


class MissingUseDepDefault(results.VersionResult, results.Warning):
    """Package dependencies with USE dependencies missing defaults."""

    def __init__(self, attr, atom, flag, pkgs, **kwargs):
        super().__init__(**kwargs)
        self.attr = attr.upper()
        self.atom = atom
        self.flag = flag
        self.pkgs = tuple(pkgs)

    @property
    def desc(self):
        s = pluralism(self.pkgs)
        pkgs = ', '.join(self.pkgs)
        return (
            f'{self.attr}="{self.atom}": USE flag {self.flag!r} missing from '
            f'package{s}: [ {pkgs} ]'
        )


class DeprecatedDep(results.VersionResult, results.Warning):
    """Package dependencies matching deprecated packages flagged in profiles/package.deprecated."""

    def __init__(self, attr, atoms, **kwargs):
        super().__init__(**kwargs)
        self.attr = attr
        self.atoms = tuple(atoms)

    @property
    def desc(self):
        ies = pluralism(self.atoms, singular='y', plural='ies')
        return f"{self.attr}: deprecated dependenc{ies}: {' '.join(self.atoms)}"


class BadDependency(results.VersionResult, results.Error):
    """Package dependency is bad for some reason."""

    def __init__(self, depset, atom, msg, **kwargs):
        super().__init__(**kwargs)
        self.depset = depset
        self.atom = str(atom)
        self.msg = msg

    @property
    def desc(self):
        return f'{self.msg}: {self.depset.upper()}="{self.atom}"'


class InvalidDepend(results.MetadataError, results.VersionResult):
    """Package has invalid DEPEND."""

    attr = 'depend'


class InvalidRdepend(results.MetadataError, results.VersionResult):
    """Package has invalid RDEPEND."""

    attr = 'rdepend'


class InvalidPdepend(results.MetadataError, results.VersionResult):
    """Package has invalid PDEPEND."""

    attr = 'pdepend'


class InvalidBdepend(results.MetadataError, results.VersionResult):
    """Package has invalid BDEPEND."""

    attr = 'bdepend'


class InvalidIdepend(results.MetadataError, results.VersionResult):
    """Package has invalid IDEPEND."""

    attr = 'idepend'


class MisplacedWeakBlocker(results.Warning, results.VersionResult):
    """Weak blocker is within a misplaced dependency class.

    Weak blockers control whether we ignore file collisions at the point of
    merge, so being (exclusively) defined in DEPEND or BDEPEND is wrong.

    Note that in cases where the weak blocker is also defined in RDEPEND, this
    warning won't be triggered, to give leeway given this is a common ebuild
    pattern.
    """

    def __init__(self, attr, atom, **kwargs):
        super().__init__(**kwargs)
        self.attr = attr.upper()
        self.atom = str(atom)

    @property
    def desc(self):
        return f'{self.attr}: misplaced weak blocker: {self.atom}'


class DependencyCheck(Check):
    """Verify dependency attributes (e.g. RDEPEND)."""

    required_addons = (addons.UseAddon,)
    known_results = frozenset([
        BadDependency, MissingPackageRevision, MissingUseDepDefault,
        UnstatedIuse, DeprecatedDep, InvalidDepend, InvalidRdepend,
        InvalidPdepend, InvalidBdepend, InvalidIdepend, MisplacedWeakBlocker,
    ])

    def __init__(self, *args, use_addon):
        super().__init__(*args)
        self.deprecated = self.options.target_repo.deprecated.match
        self.iuse_filter = use_addon.get_filter()
        self.conditional_ops = {'?', '='}
        self.use_defaults = {'(+)', '(-)'}

    def _check_use_deps(self, attr, atom):
        """Check dependencies for missing USE dep defaults."""
        stripped_use = []
        for x in atom.use:
            if x[-1] in self.conditional_ops:
                x = x[:-1]
            if x[-3:] in self.use_defaults:
                continue
            stripped_use.append(x.lstrip('!-'))
        if stripped_use:
            missing_use_deps = defaultdict(set)
            for pkg in self.options.search_repo.match(atom.no_usedeps):
                for use in stripped_use:
                    if use not in pkg.iuse_effective:
                        missing_use_deps[use].add(pkg.versioned_atom)
            return missing_use_deps
        return {}

    def feed(self, pkg):
        deprecated = defaultdict(set)

        weak_blocks = defaultdict(set)

        for attr in sorted(x.lower() for x in pkg.eapi.dep_keys):
            try:
                deps = getattr(pkg, attr)
            except MetadataException as e:
                cls = globals()[f'Invalid{attr.capitalize()}']
                yield cls(attr, e.msg(), pkg=pkg)
                continue

            nodes, unstated = self.iuse_filter(
                (atom_cls, boolean.OrRestriction), pkg, deps, attr=attr)
            yield from unstated

            for node in nodes:
                if isinstance(node, boolean.OrRestriction):
                    in_or_restriction = True
                else:
                    in_or_restriction = False

                for atom in iflatten_instance(node, (atom_cls,)):
                    # Skip reporting blockers on deprecated packages; the primary
                    # purpose of deprecations is to get rid of dependencies
                    # holding them in the repo.
                    if not atom.blocks and self.deprecated(atom):
                        # verify all matching packages are deprecated
                        pkgs = self.options.search_repo.match(atom.no_usedeps)
                        if all(self.deprecated(x.versioned_atom) for x in pkgs):
                            deprecated[attr].add(atom)

                    if in_or_restriction and atom.slot_operator == '=':
                        yield BadDependency(
                            attr, atom, '= slot operator used inside || block', pkg=pkg)

                    if pkg.eapi.options.has_use_dep_defaults and atom.use is not None:
                        missing_use_deps = self._check_use_deps(attr, atom)
                        for use, atoms in missing_use_deps.items():
                            pkgs = (x.cpvstr for x in sorted(atoms))
                            yield MissingUseDepDefault(attr, str(atom), use, pkgs, pkg=pkg)

                    if atom.op == '=' and not atom.revision:
                        yield MissingPackageRevision(attr, str(atom), pkg=pkg)

                    if atom.blocks:
                        if atom.match(pkg):
                            yield BadDependency(attr, atom, "package blocks itself", pkg=pkg)
                        elif atom.slot_operator == '=':
                            yield BadDependency(
                                attr, atom, '= slot operator used in blocker', pkg=pkg)
                        elif not atom.blocks_strongly:
                            weak_blocks[attr].add(atom)

        for attr in ('depend', 'bdepend'):
            weak_blocks[attr].difference_update(weak_blocks['rdepend'])
        weak_blocks['idepend'].difference_update(weak_blocks['rdepend'], weak_blocks['depend'])
        for attr in ('depend', 'bdepend', 'idepend', 'pdepend'):
            for atom in weak_blocks[attr]:
                yield MisplacedWeakBlocker(attr, atom, pkg=pkg)

        for attr, atoms in deprecated.items():
            yield DeprecatedDep(attr.upper(), map(str, sorted(atoms)), pkg=pkg)


class OutdatedBlocker(results.VersionResult, results.Info):
    """Blocker dependency removed at least two years ago from the tree.

    Note that this ignores slot/subslot deps and USE deps in blocker atoms.
    """

    def __init__(self, attr, atom, age, **kwargs):
        super().__init__(**kwargs)
        self.attr = attr
        self.atom = atom
        self.age = float(age)

    @property
    def desc(self):
        return (
            f'outdated blocker {self.attr}="{self.atom}": '
            f'last match removed {self.age} years ago'
        )


class NonexistentBlocker(results.VersionResult, results.Warning):
    """No matches for blocker dependency in repo history.

    For the gentoo repo this means it was either removed before the CVS -> git
    transition (which occurred around 2015-08-08) or it never existed at all.

    Note that this ignores slot/subslot deps and USE deps in blocker atoms.
    """

    def __init__(self, attr, atom, **kwargs):
        super().__init__(**kwargs)
        self.attr = attr
        self.atom = atom

    @property
    def desc(self):
        return (
            f'nonexistent blocker {self.attr}="{self.atom}": '
            'no matches in repo history'
        )


class OutdatedBlockersCheck(Check):
    """Check for outdated and nonexistent blocker dependencies."""

    required_addons = (addons.git.GitAddon,)
    known_results = frozenset([OutdatedBlocker, NonexistentBlocker])

    def __init__(self, *args, git_addon):
        super().__init__(*args)
        self.today = datetime.today()
        self.existence_repo = git_addon.cached_repo(addons.git.GitRemovedRepo)

    def feed(self, pkg):
        outdated_blockers = defaultdict(set)
        nonexistent_blockers = defaultdict(set)

        for attr in sorted(x.lower() for x in pkg.eapi.dep_keys):
            blockers = (x for x in iflatten_instance(getattr(pkg, attr), atom_cls) if x.blocks)
            for atom in blockers:
                if atom.op == '=*':
                    atom_str = f"={atom.cpvstr}*"
                else:
                    atom_str = atom.op + atom.cpvstr
                unblocked = atom_cls(atom_str)
                if not self.options.search_repo.match(unblocked):
                    if matches := self.existence_repo.match(unblocked):
                        removal = max(x.time for x in matches)
                        removal = datetime.fromtimestamp(removal)
                        years = (self.today - removal).days / 365
                        if years >= 2:
                            outdated_blockers[attr].add((atom, round(years, 2)))
                    else:
                        nonexistent_blockers[attr].add(atom)

        for attr, data in outdated_blockers.items():
            for atom, years in sorted(data):
                yield OutdatedBlocker(attr.upper(), str(atom), years, pkg=pkg)
        for attr, atoms in nonexistent_blockers.items():
            for atom in sorted(atoms):
                yield NonexistentBlocker(attr.upper(), str(atom), pkg=pkg)


class BadKeywords(results.VersionResult, results.Warning):
    """Packages using ``-*`` should use package.mask instead."""

    desc = 'use package.mask or undefined keywords instead of KEYWORDS="-*"'


class UnknownKeywords(results.VersionResult, results.Error):
    """Packages using unknown KEYWORDS."""

    def __init__(self, keywords, **kwargs):
        super().__init__(**kwargs)
        self.keywords = tuple(keywords)

    @property
    def desc(self):
        return f"unknown KEYWORDS: {', '.join(map(repr, self.keywords))}"


class OverlappingKeywords(results.VersionResult, results.Style):
    """Packages having overlapping arch and ~arch KEYWORDS."""

    def __init__(self, keywords, **kwargs):
        super().__init__(**kwargs)
        self.keywords = keywords

    @property
    def desc(self):
        return f"overlapping KEYWORDS: {self.keywords}"


class DuplicateKeywords(results.VersionResult, results.Style):
    """Packages having duplicate KEYWORDS."""

    def __init__(self, keywords, **kwargs):
        super().__init__(**kwargs)
        self.keywords = tuple(keywords)

    @property
    def desc(self):
        return f"duplicate KEYWORDS: {', '.join(self.keywords)}"


class UnsortedKeywords(results.VersionResult, results.Style):
    """Packages with unsorted KEYWORDS.

    KEYWORDS should be sorted in alphabetical order with prefix keywords (those
    with hyphens in them, e.g. amd64-fbsd) after regular arches and globs (e.g. ``-*``)
    before them.
    """

    def __init__(self, keywords, sorted_keywords=(), **kwargs):
        super().__init__(**kwargs)
        self.keywords = tuple(keywords)
        self.sorted_keywords = tuple(sorted_keywords)

    @property
    def desc(self):
        if self.sorted_keywords:
            # verbose mode shows list of properly sorted keywords
            return (
                f"\n\tunsorted KEYWORDS: {', '.join(self.keywords)}"
                f"\n\tsorted KEYWORDS: {', '.join(self.sorted_keywords)}"
            )
        return f"unsorted KEYWORDS: {', '.join(self.keywords)}"


class VirtualKeywordsUpdate(results.VersionResult, results.Info):
    """Virtual packages with keywords that can be updated to match dependencies."""

    def __init__(self, keywords, **kwargs):
        super().__init__(**kwargs)
        self.keywords = tuple(keywords)

    @property
    def desc(self):
        s = pluralism(self.keywords)
        keywords = ', '.join(self.keywords)
        return f"KEYWORDS update{s} available: {keywords}"


class KeywordsCheck(Check):
    """Check package keywords for sanity; empty keywords, and -* are flagged."""

    required_addons = (addons.UseAddon, addons.KeywordsAddon)
    known_results = frozenset([
        BadKeywords, UnknownKeywords, OverlappingKeywords, DuplicateKeywords,
        UnsortedKeywords, VirtualKeywordsUpdate,
    ])

    def __init__(self, *args, use_addon, keywords_addon):
        super().__init__(*args)
        self.iuse_filter = use_addon.get_filter()
        self.keywords = keywords_addon

    def feed(self, pkg):
        if pkg.keywords == ('-*',):
            yield BadKeywords(pkg)
        else:
            # check for unknown keywords
            unknown = set(pkg.keywords) - self.keywords.valid
            # portage-only KEYWORDS are allowed in overlays
            if not self.options.gentoo_repo:
                unknown -= self.keywords.portage
            if unknown:
                yield UnknownKeywords(sorted(unknown), pkg=pkg)

            # check for overlapping keywords
            unstable = {x[1:] for x in pkg.keywords if x[0] == '~'}
            stable = {x for x in pkg.keywords if x[0] != '~'}
            if overlapping := unstable & stable:
                keywords = ', '.join(map(
                    str, sorted(zip(overlapping, ('~' + x for x in overlapping)))))
                yield OverlappingKeywords(keywords, pkg=pkg)

            # check for duplicate keywords
            duplicates = set()
            seen = set()
            for x in pkg.keywords:
                if x not in seen:
                    seen.add(x)
                else:
                    duplicates.add(x)
            if duplicates:
                yield DuplicateKeywords(sort_keywords(duplicates), pkg=pkg)

            # check for unsorted keywords
            if pkg.sorted_keywords != pkg.keywords:
                if self.options.verbosity < 1:
                    yield UnsortedKeywords(pkg.keywords, pkg=pkg)
                else:
                    yield UnsortedKeywords(
                        pkg.keywords, sorted_keywords=pkg.sorted_keywords, pkg=pkg)

            if pkg.category == 'virtual':
                dep_keywords = defaultdict(set)
                rdepend, _ = self.iuse_filter((atom_cls,), pkg, pkg.rdepend)
                for dep in set(rdepend):
                    for p in self.options.search_repo.match(dep.no_usedeps):
                        dep_keywords[dep].update(
                            x for x in p.keywords if x.lstrip('~') in self.keywords.arches)
                if dep_keywords:
                    dep_keywords = set.intersection(*dep_keywords.values())
                    pkg_keywords = set(pkg.keywords)
                    pkg_keywords.update(f'~{x}' for x in pkg.keywords if x[0] != '~')
                    if keywords := dep_keywords - pkg_keywords:
                        yield VirtualKeywordsUpdate(sort_keywords(keywords), pkg=pkg)


class MissingUri(results.VersionResult, results.Warning):
    """RESTRICT=fetch isn't set, yet no full URI exists."""

    def __init__(self, filenames, **kwargs):
        super().__init__(**kwargs)
        self.filenames = tuple(filenames)

    @property
    def desc(self):
        s = pluralism(self.filenames)
        filenames = ', '.join(map(repr, self.filenames))
        return f'unfetchable file{s}: {filenames}'


class UnknownMirror(results.VersionResult, results.Error):
    """URI uses an unknown mirror."""

    def __init__(self, mirror, uri, **kwargs):
        super().__init__(**kwargs)
        self.mirror = mirror
        self.uri = uri

    @property
    def desc(self):
        return f'unknown mirror {self.mirror!r} from URI {self.uri!r}'


class BadProtocol(results.VersionResult, results.Error):
    """URI uses an unsupported protocol.

    Valid protocols are currently: http, https, and ftp
    """

    def __init__(self, protocol, uris, **kwargs):
        super().__init__(**kwargs)
        self.protocol = protocol
        self.uris = tuple(uris)

    @property
    def desc(self):
        s = pluralism(self.uris)
        uris = ', '.join(map(repr, self.uris))
        return f'bad protocol {self.protocol!r} in URI{s}: {uris}'


class RedundantUriRename(results.VersionResult, results.Style):
    """URI uses a redundant rename that doesn't change the filename."""

    def __init__(self, pkg, message):
        super().__init__(pkg=pkg)
        self.message = message

    @property
    def desc(self):
        return self.message


class BadFilename(results.VersionResult, results.Warning):
    """URI uses unspecific or poor filename(s).

    Archive filenames should be disambiguated using ``->`` to rename them.
    """

    def __init__(self, filenames, **kwargs):
        super().__init__(**kwargs)
        self.filenames = tuple(filenames)

    @property
    def desc(self):
        s = pluralism(self.filenames)
        filenames = ', '.join(self.filenames)
        return f'bad filename{s}: [ {filenames} ]'


class TarballAvailable(results.VersionResult, results.Style):
    """URI uses .zip archive when .tar* is available.

    Tarballs should be preferred over zip archives due to better compression
    and no extra unpack dependencies.
    """

    def __init__(self, uris, **kwargs):
        super().__init__(**kwargs)
        self.uris = tuple(uris)

    @property
    def desc(self):
        s = pluralism(self.uris)
        uris = ' '.join(self.uris)
        return f'zip archive{s} used when tarball available: [ {uris} ]'


class InvalidSrcUri(results.MetadataError, results.VersionResult):
    """Package's SRC_URI is invalid."""

    attr = 'fetchables'


class SrcUriCheck(Check):
    """SRC_URI related checks.

    Verify that URIs are valid, fetchable, using a supported protocol, and
    don't use unspecific filenames.
    """

    required_addons = (addons.UseAddon,)
    known_results = frozenset([
        BadFilename, BadProtocol, MissingUri, InvalidSrcUri,
        RedundantUriRename, TarballAvailable, UnknownMirror, UnstatedIuse,
    ])

    valid_protos = frozenset(["http", "https", "ftp"])

    def __init__(self, *args, use_addon):
        super().__init__(*args)
        self.iuse_filter = use_addon.get_filter('fetchables')
        self.zip_to_tar_re = re.compile(
            r'https?://(github\.com/.*?/.*?/archive/.+\.zip|'
            r'gitlab\.com/.*?/.*?/-/archive/.+\.zip)')

    def feed(self, pkg):
        lacks_uri = set()
        # duplicate entries are possible.
        seen = set()
        bad_filenames = set()
        tarball_available = set()

        report_uris = LogMap('pkgcore.log.logger.info', partial(RedundantUriRename, pkg))
        with LogReports(report_uris) as log_reports:
            fetchables, unstated = self.iuse_filter(
                (fetchable,), pkg,
                pkg.generate_fetchables(
                    allow_missing_checksums=True, ignore_unknown_mirrors=True,
                    skip_default_mirrors=True))
        yield from log_reports

        yield from unstated
        for f_inst, restrictions in fetchables.items():
            if f_inst.filename in seen:
                continue
            seen.add(f_inst.filename)

            mirrors = f_inst.uri.visit_mirrors(treat_default_as_mirror=False)
            unknown_mirrors = [
                (m, sub_uri) for m, sub_uri in mirrors if isinstance(m, unknown_mirror)]
            for mirror, sub_uri in unknown_mirrors:
                uri = f"{mirror}/{sub_uri}"
                yield UnknownMirror(mirror.mirror_name, uri, pkg=pkg)

            # Check for unspecific filenames of the form ${PN}.ext, ${PV}.ext,
            # and v${PV}.ext as well as archives named using only the raw git
            # commit hash.
            PN = re.escape(pkg.PN)
            PV = re.escape(pkg.PV)
            exts = pkg.eapi.archive_exts_regex_pattern
            bad_filenames_re = rf'^({PN}|v?{PV}|[0-9a-f]{{40}}){exts}$'
            if re.match(bad_filenames_re, f_inst.filename):
                bad_filenames.add(f_inst.filename)

            restricts = set().union(*(x.vals for x in restrictions if not x.negate))
            if not f_inst.uri and 'fetch' not in pkg.restrict.evaluate_depset(restricts):
                lacks_uri.add(f_inst.filename)
            else:
                bad_protocols = defaultdict(set)
                for uri in f_inst.uri:
                    i = uri.find("://")
                    if i == -1:
                        lacks_uri.add(uri)
                    elif uri[:i] not in self.valid_protos:
                        bad_protocols[uri[:i]].add(uri)
                    elif self.zip_to_tar_re.match(uri):
                        tarball_available.add(uri)
                for protocol, uris in bad_protocols.items():
                    yield BadProtocol(protocol, sorted(uris), pkg=pkg)

        if lacks_uri:
            yield MissingUri(sorted(lacks_uri), pkg=pkg)
        if bad_filenames:
            yield BadFilename(sorted(bad_filenames), pkg=pkg)
        if tarball_available:
            yield TarballAvailable(sorted(tarball_available), pkg=pkg)


class BadDescription(results.VersionResult, results.Style):
    """Package's description is bad for some reason."""

    def __init__(self, msg, pkg_desc=None, **kwargs):
        super().__init__(**kwargs)
        self.msg = msg
        self.pkg_desc = pkg_desc

    @property
    def desc(self):
        pkg_desc = f'DESCRIPTION="{self.pkg_desc}" ' if self.pkg_desc else ''
        return f'{pkg_desc}{self.msg}'


class DescriptionCheck(Check):
    """DESCRIPTION checks.

    Check on length (<=80), too short (<10), or generic (lifted from eclass or
    just using the package's name).
    """

    known_results = frozenset([BadDescription])

    def feed(self, pkg):
        desc = pkg.description
        s = desc.lower()
        if s.startswith("based on") and "eclass" in s:
            yield BadDescription("generic eclass defined description", pkg_desc=desc, pkg=pkg)
        elif s in (pkg.package.lower(), pkg.key.lower()):
            yield BadDescription("generic package description", pkg_desc=desc, pkg=pkg)
        else:
            desc_len = len(desc)
            if not desc_len:
                yield BadDescription("empty/unset", pkg=pkg)
            elif desc_len > 80:
                yield BadDescription("over 80 chars in length", pkg=pkg)
            elif desc_len < 10:
                yield BadDescription("under 10 chars in length", pkg_desc=desc, pkg=pkg)


class BadHomepage(results.VersionResult, results.Warning):
    """A package's HOMEPAGE is bad for some reason.

    See the HOMEPAGE ebuild variable entry in the devmanual [#]_ for more
    information.

    .. [#] https://devmanual.gentoo.org/ebuild-writing/variables/#ebuild-defined-variables
    """

    def __init__(self, msg, **kwargs):
        super().__init__(**kwargs)
        self.msg = msg

    @property
    def desc(self):
        return self.msg


class HomepageCheck(Check):
    """HOMEPAGE checks."""

    known_results = frozenset([BadHomepage])

    # categories for ebuilds that should lack HOMEPAGE
    missing_categories = frozenset(['virtual', 'acct-group', 'acct-user'])
    # generic sites that shouldn't be used for HOMEPAGE
    generic_sites = frozenset(['https://www.gentoo.org', 'https://gentoo.org'])

    def feed(self, pkg):
        if not pkg.homepage:
            if pkg.category not in self.missing_categories:
                yield BadHomepage('HOMEPAGE empty/unset', pkg=pkg)
        else:
            if pkg.category in self.missing_categories:
                yield BadHomepage(
                    f'HOMEPAGE should be undefined for {pkg.category!r} packages', pkg=pkg)
            else:
                for homepage in pkg.homepage:
                    if homepage.rstrip('/') in self.generic_sites:
                        yield BadHomepage(f'unspecific HOMEPAGE: {homepage}', pkg=pkg)
                    else:
                        i = homepage.find('://')
                        if i == -1:
                            yield BadHomepage(f'HOMEPAGE={homepage!r} lacks protocol', pkg=pkg)
                        elif homepage[:i] not in SrcUriCheck.valid_protos:
                            yield BadHomepage(
                                f'HOMEPAGE={homepage!r} uses unsupported '
                                f'protocol {homepage[:i]!r}',
                                pkg=pkg)


class UnknownRestrict(results.VersionResult, results.Warning):
    """Package's RESTRICT metadata has unknown entries."""

    def __init__(self, restricts, **kwargs):
        super().__init__(**kwargs)
        self.restricts = tuple(restricts)

    @property
    def desc(self):
        restricts = ' '.join(self.restricts)
        return f'unknown RESTRICT="{restricts}"'


class UnknownProperties(results.VersionResult, results.Warning):
    """Package's PROPERTIES metadata has unknown entries."""

    def __init__(self, properties, **kwargs):
        super().__init__(**kwargs)
        self.properties = tuple(properties)

    @property
    def desc(self):
        properties = ' '.join(self.properties)
        return f'unknown PROPERTIES="{properties}"'


class InvalidRestrict(results.MetadataError, results.VersionResult):
    """Package's RESTRICT is invalid."""

    attr = 'restrict'


class InvalidProperties(results.MetadataError, results.VersionResult):
    """Package's PROPERTIES is invalid."""

    attr = 'properties'


class _RestrictPropertiesCheck(Check):
    """Generic check for RESTRICT and PROPERTIES."""

    _attr = None
    _unknown_result_cls = None
    required_addons = (addons.UseAddon,)

    def __init__(self, *args, use_addon):
        super().__init__(*args)
        self.filter = use_addon.get_filter(self._attr)

        # pull allowed values from a repo and its masters
        allowed = []
        for repo in self.options.target_repo.trees:
            allowed.extend(getattr(repo.config, f'{self._attr}_allowed'))
        self.allowed = frozenset(allowed)

    def feed(self, pkg):
        values, unstated = self.filter((str,), pkg, getattr(pkg, self._attr))
        yield from unstated

        # skip if target repo or its masters don't define allowed values
        if self.allowed and values:
            if unknown := set(values).difference(self.allowed):
                yield self._unknown_result_cls(sorted(unknown), pkg=pkg)


class RestrictCheck(_RestrictPropertiesCheck):
    """RESTRICT related checks."""

    known_results = frozenset([UnknownRestrict, UnstatedIuse, InvalidRestrict])
    _attr = 'restrict'
    _unknown_result_cls = UnknownRestrict


class PropertiesCheck(_RestrictPropertiesCheck):
    """PROPERTIES related checks."""

    known_results = frozenset([UnknownProperties, UnstatedIuse, InvalidProperties])
    _attr = 'properties'
    _unknown_result_cls = UnknownProperties


class MissingTestRestrict(results.VersionResult, results.Warning):
    """Missing ``RESTRICT="!test? ( test )"``.

    Traditionally, it was assumed that ``IUSE=test`` is a special flag that is
    implicitly enabled when running ``src_test()`` is enabled. However, this is
    not standarized and packages need to explicitly specify
    ``RESTRICT="!test? ( test )"`` in order to guarantee that test phase will
    be skipped when the flag is disabled and therefore test dependencies may
    not be installed.
    """

    @property
    def desc(self):
        return 'missing RESTRICT="!test? ( test )" with IUSE=test'


class RestrictTestCheck(Check):
    """Check whether packages specify RESTRICT="!test? ( test )"."""

    known_results = frozenset([MissingTestRestrict])

    def __init__(self, *args):
        super().__init__(*args)
        # create "!test? ( test )" conditional to match restrictions against
        self.test_restrict = packages.Conditional(
            'use', values.ContainmentMatch2('test', negate=True), ['test'])

    def feed(self, pkg):
        if 'test' not in pkg.iuse:
            return

        # conditional is unnecessary if it already exists or is in unconditional form
        for r in pkg.restrict:
            if r in ('test', self.test_restrict):
                return

        yield MissingTestRestrict(pkg=pkg)


class MissingUnpackerDep(results.VersionResult, results.Warning):
    """Missing dependency on a required unpacker package.

    Package uses an archive format for which an unpacker is not provided by the
    system set, and lacks an explicit dependency on the unpacker package.
    """

    def __init__(self, eapi, filenames, unpackers, **kwargs):
        super().__init__(**kwargs)
        self.eapi = eapi
        self.filenames = tuple(filenames)
        self.unpackers = tuple(unpackers)

    @property
    def desc(self):
        # determine proper dep type from pkg EAPI
        eapi_obj = get_eapi(self.eapi)
        dep_type = 'BDEPEND' if 'BDEPEND' in eapi_obj.metadata_keys else 'DEPEND'

        if len(self.unpackers) == 1:
            dep = self.unpackers[0]
        else:
            dep = f"|| ( {' '.join(self.unpackers)} )"

        s = pluralism(self.filenames)
        filenames = ', '.join(self.filenames)
        return f'missing {dep_type}="{dep}" for SRC_URI archive{s}: [ {filenames} ]'


class MissingUnpackerDepCheck(Check):
    """Check whether package is missing unpacker dependencies."""

    known_results = frozenset([MissingUnpackerDep])
    required_addons = (addons.UseAddon,)

    non_system_unpackers = ImmutableDict({
        '.zip': frozenset(['app-arch/unzip']),
        '.7z': frozenset(['app-arch/p7zip']),
        '.rar': frozenset(['app-arch/rar', 'app-arch/unrar']),
        '.lha': frozenset(['app-arch/lha']),
        '.lzh': frozenset(['app-arch/lha']),
    })

    def __init__(self, *args, use_addon):
        super().__init__(*args)
        self.dep_filter = use_addon.get_filter()
        self.fetch_filter = use_addon.get_filter('fetchables')

    def feed(self, pkg):
        # ignore conditionals
        fetchables, _ = self.fetch_filter(
            (fetchable,), pkg,
            pkg.generate_fetchables(
                allow_missing_checksums=True, ignore_unknown_mirrors=True,
                skip_default_mirrors=True))

        missing_unpackers = defaultdict(set)

        # scan for fetchables that require unpackers not in the system set
        for f in fetchables:
            _, ext = os.path.splitext(f.filename.lower())
            if ext in self.non_system_unpackers:
                missing_unpackers[self.non_system_unpackers[ext]].add(f.filename)

        # toss all the potentially missing unpackers that properly include deps
        if missing_unpackers:
            for dep_type in ('bdepend', 'depend'):
                deps, _ = self.dep_filter((atom_cls,), pkg, getattr(pkg, dep_type))
                deps = {x.key for x in deps}
                for unpackers in list(missing_unpackers.keys()):
                    if unpackers.intersection(deps):
                        missing_unpackers.pop(unpackers, None)

        for unpackers, filenames in missing_unpackers.items():
            yield MissingUnpackerDep(
                str(pkg.eapi), sorted(filenames), sorted(unpackers), pkg=pkg)
