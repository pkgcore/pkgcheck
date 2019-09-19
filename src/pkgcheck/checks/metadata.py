import os
import re
from collections import defaultdict
from datetime import datetime
from difflib import SequenceMatcher
from itertools import chain

from pkgcore.ebuild import atom
from pkgcore.ebuild.atom import atom as atom_cls
from pkgcore.ebuild.eapi import get_eapi
from pkgcore.ebuild.misc import sort_keywords
from pkgcore.fetch import fetchable, unknown_mirror
from pkgcore.package.errors import MetadataException
from pkgcore.restrictions import packages, values, boolean
from snakeoil.klass import jit_attr
from snakeoil.mappings import ImmutableDict
from snakeoil.sequences import iflatten_instance
from snakeoil.strings import pluralism as _pl

from .. import addons, base, sources
from ..addons import UnstatedIUSE
from ..base import MetadataError
from .visibility import FakeConfigurable


class MissingLicense(base.VersionedResult, base.Error):
    """Used license(s) have no matching license file(s)."""

    def __init__(self, licenses, **kwargs):
        super().__init__(**kwargs)
        self.licenses = tuple(licenses)

    @property
    def desc(self):
        licenses = ', '.join(self.licenses)
        return f"no matching license{_pl(self.licenses)}: [ {licenses} ]"


class MissingLicenseRestricts(base.VersionedResult, base.Error):
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


class UnnecessaryLicense(base.VersionedResult, base.Warning):
    """LICENSE defined for package that is license-less."""

    @property
    def desc(self):
        return f"{self.category!r} packages shouldn't define LICENSE"


class LicenseMetadataCheck(base.Check):
    """LICENSE validity checks."""

    known_results = (
        MetadataError, MissingLicense, UnnecessaryLicense, UnstatedIUSE,
        MissingLicenseRestricts,
    )
    feed_type = base.versioned_feed

    # categories for ebuilds that can lack LICENSE settings
    unlicensed_categories = frozenset(['virtual', 'acct-group', 'acct-user'])

    required_addons = (addons.UseAddon, addons.ProfileAddon)

    def __init__(self, options, iuse_handler, profiles):
        super().__init__(options)
        self.iuse_filter = iuse_handler.get_filter('license')
        self.eula = self.options.target_repo.licenses.groups.get('EULA')
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
                restricts = frozenset(chain.from_iterable(
                    x.vals for x in restrictions if not x.negate))
                license_restrictions = pkg.restrict.evaluate_depset(restricts)
                missing_restricts = []
                if 'bindist' not in license_restrictions:
                    missing_restricts.append('bindist')
                if not self.mirror_restricts.intersection(license_restrictions):
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
                yield MetadataError('license', 'no license defined', pkg=pkg)
        else:
            licenses.difference_update(pkg.repo.licenses)
            if licenses:
                yield MissingLicense(sorted(licenses), pkg=pkg)
            elif pkg.category in self.unlicensed_categories:
                yield UnnecessaryLicense(pkg=pkg)


class _UseFlagsResult(base.VersionedResult, base.Error):
    """Generic USE flags result."""

    _type = None

    def __init__(self, flags, **kwargs):
        super().__init__(**kwargs)
        self.flags = tuple(flags)

    @property
    def desc(self):
        flags = ', '.join(map(repr, sorted(self.flags)))
        return f'{self._type} USE flag{_pl(self.flags)}: {flags}'


class InvalidUseFlags(_UseFlagsResult):
    """Package IUSE contains invalid USE flags."""

    _type = 'invalid'

class UnknownUseFlags(_UseFlagsResult):
    """Package IUSE contains unknown USE flags."""

    _type = 'unknown'


class IUSEMetadataCheck(base.Check):
    """IUSE validity checks."""

    feed_type = base.versioned_feed
    required_addons = (addons.UseAddon,)
    known_results = (InvalidUseFlags, UnknownUseFlags)

    def __init__(self, options, iuse_handler):
        super().__init__(options)
        self.iuse_handler = iuse_handler

    def feed(self, pkg):
        invalid = [x for x in pkg.iuse_stripped if not atom.valid_use_flag.match(x)]
        if invalid:
            yield InvalidUseFlags(invalid, pkg=pkg)

        if not self.iuse_handler.ignore:
            unknown = pkg.iuse_stripped.difference(self.iuse_handler.allowed_iuse(pkg))
            unknown = unknown.difference(invalid)
            if unknown:
                yield UnknownUseFlags(unknown, pkg=pkg)


class _EAPIResult(base.VersionedResult):
    """Generic EAPI result."""

    _type = None

    def __init__(self, eapi, **kwargs):
        super().__init__(**kwargs)
        self.eapi = str(eapi)

    @property
    def desc(self):
        return f"uses {self._type} EAPI {self.eapi}"


class DeprecatedEAPI(_EAPIResult, base.Warning):
    """Package's EAPI is deprecated according to repo metadata."""

    _type = 'deprecated'


class BannedEAPI(_EAPIResult, base.Error):
    """Package's EAPI is banned according to repo metadata."""

    _type = 'banned'


class MetadataCheck(base.Check):
    """Scan for packages with banned/deprecated EAPIs or bad metadata."""

    feed_type = base.versioned_feed
    known_results = (DeprecatedEAPI, BannedEAPI, MetadataError)

    def feed(self, pkg):
        eapi_str = str(pkg.eapi)
        if eapi_str in self.options.target_repo.config.eapis_banned:
            yield BannedEAPI(pkg.eapi, pkg=pkg)
        elif eapi_str in self.options.target_repo.config.eapis_deprecated:
            yield DeprecatedEAPI(pkg.eapi, pkg=pkg)

    def finish(self):
        # TODO: Move this somewhere that's consistently triggered after running
        # all tests on a package set during the feed stage.
        #
        # report all masked pkgs due to invalid EAPIs and other bad metadata
        for pkg in self.options.target_repo._masked:
            e = pkg.data
            if isinstance(e, MetadataException):
                yield MetadataError(
                    e.attr, e.msg(verbosity=self.options.verbosity),
                    pkg=pkg.versioned_atom)


class RequiredUseDefaults(base.VersionedResult, base.Warning):
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


class RequiredUSEMetadataCheck(base.Check):
    """REQUIRED_USE validity checks."""

    feed_type = base.versioned_feed
    # only run the check for EAPI 4 and above
    source = (sources.RestrictionRepoSource, (
        packages.PackageRestriction('eapi', values.GetAttrRestriction(
            'options.has_required_use', values.FunctionRestriction(bool))),))
    required_addons = (addons.UseAddon, addons.ProfileAddon)
    known_results = (MetadataError, RequiredUseDefaults, UnstatedIUSE)

    def __init__(self, options, iuse_handler, profiles):
        super().__init__(options)
        self.iuse_filter = iuse_handler.get_filter('required_use')
        self.profiles = profiles

    def feed(self, pkg):
        # check REQUIRED_USE for invalid nodes
        _nodes, unstated = self.iuse_filter((str,), pkg, pkg.required_use)
        yield from unstated

        # check both stable/unstable profiles for stable KEYWORDS and only
        # unstable profiles for unstable KEYWORDS
        keywords = []
        for keyword in pkg.keywords:
            if keyword[0] != '~':
                keywords.append(keyword)
            keywords.append('~' + keyword.lstrip('~'))

        # check USE defaults (pkg IUSE defaults + profile USE) against
        # REQUIRED_USE for all profiles matching a pkg's KEYWORDS
        failures = defaultdict(list)
        for keyword in keywords:
            for profile in self.profiles.get(keyword, ()):
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


class UnusedLocalUSE(base.PackageResult, base.Warning):
    """Unused local USE flag(s)."""

    def __init__(self, flags, **kwargs):
        super().__init__(**kwargs)
        self.flags = tuple(flags)

    @property
    def desc(self):
        return "metadata.xml unused local USE flag%s: [ %s ]" % (
            _pl(self.flags), ', '.join(self.flags))


class MatchingGlobalUSE(base.PackageResult, base.Error):
    """Local USE flag description matches a global USE flag."""

    def __init__(self, flag, **kwargs):
        super().__init__(**kwargs)
        self.flag = flag

    @property
    def desc(self):
        return f"local USE flag matches a global: {self.flag!r}"


class ProbableGlobalUSE(base.PackageResult, base.Warning):
    """Local USE flag description closely matches a global USE flag."""

    def __init__(self, flag, **kwargs):
        super().__init__(**kwargs)
        self.flag = flag

    @property
    def desc(self):
        return f"local USE flag closely matches a global: {self.flag!r}"


class ProbableUseExpand(base.PackageResult, base.Warning):
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


class UnderscoreInUseFlag(base.PackageResult, base.Warning):
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


class LocalUSECheck(base.Check):
    """Check local USE flags in metadata.xml for various issues."""

    feed_type = base.package_feed
    scope = base.package_scope
    required_addons = (addons.UseAddon,)
    known_results = (
        UnusedLocalUSE, MatchingGlobalUSE, ProbableGlobalUSE,
        ProbableUseExpand, UnderscoreInUseFlag, UnstatedIUSE,
    )

    def __init__(self, options, use_handler):
        super().__init__(options)
        self.iuse_handler = use_handler
        self.global_use = {
            flag: desc for matcher, (flag, desc) in options.target_repo.config.use_desc}

        self.use_expand_groups = dict()
        for key in options.target_repo.config.use_expand_desc.keys():
            self.use_expand_groups[key] = {
                flag for flag, desc in options.target_repo.config.use_expand_desc[key]}

    def feed(self, pkgs):
        pkg = pkgs[0]
        local_use = pkg.local_use

        for flag, desc in local_use.items():
            if flag in self.global_use:
                ratio = SequenceMatcher(None, desc, self.global_use[flag]).ratio()
                if ratio == 1.0:
                    yield MatchingGlobalUSE(flag, pkg=pkg)
                elif ratio >= 0.75:
                    yield ProbableGlobalUSE(flag, pkg=pkg)
            else:
                for group in self.use_expand_groups:
                    if flag.startswith(f'{group}_'):
                        if flag not in self.use_expand_groups[group]:
                            yield ProbableUseExpand(flag, group.upper(), pkg=pkg)
                        break
                else:
                    if '_' in flag:
                        yield UnderscoreInUseFlag(flag, pkg=pkg)

        unused = set(local_use)
        for pkg in pkgs:
            unused.difference_update(pkg.iuse_stripped)
        if unused:
            yield UnusedLocalUSE(sorted(unused), pkg=pkg)


class MissingSlotDep(base.VersionedResult, base.Warning):
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


class MissingSlotDepCheck(base.Check):
    """Check for missing slot dependencies."""

    feed_type = base.versioned_feed
    # only run the check for EAPI 5 and above
    source = (sources.RestrictionRepoSource, (
        packages.PackageRestriction('eapi', values.GetAttrRestriction(
            'options.sub_slotting', values.FunctionRestriction(bool))),))
    required_addons = (addons.UseAddon,)
    known_results = (MissingSlotDep,)

    def __init__(self, options, iuse_handler):
        super().__init__(options)
        self.iuse_filter = iuse_handler.get_filter()

    def feed(self, pkg):
        rdepend, _ = self.iuse_filter((atom_cls,), pkg, pkg.rdepend)
        depend, _ = self.iuse_filter((atom_cls,), pkg, pkg.depend)

        # skip deps that are blockers or have explicit slots/slot operators
        for dep in (x for x in set(rdepend).intersection(depend) if not
                    (x.blocks or x.slot is not None or x.slot_operator is not None)):
            dep_slots = set(x.slot for x in pkg.repo.itermatch(dep.unversioned_atom))
            if len(dep_slots) > 1:
                yield MissingSlotDep(str(dep), sorted(dep_slots), pkg=pkg)


class MissingPackageRevision(base.VersionedResult, base.Warning):
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
        return f'{self.dep}="{self.atom}": "=" operator used without package revision'


class MissingUseDepDefault(base.VersionedResult, base.Warning):
    """Package dependencies with USE dependencies missing defaults."""

    def __init__(self, attr, atom, flag, pkgs, **kwargs):
        super().__init__(**kwargs)
        self.attr = attr.upper()
        self.atom = atom
        self.flag = flag
        self.pkgs = tuple(pkgs)

    @property
    def desc(self):
        return (
            f'{self.attr}="{self.atom}": USE flag {self.flag!r} missing from '
            f"package{_pl(self.pkgs)}: [ {', '.join(self.pkgs)} ]"
        )


class OutdatedBlocker(base.VersionedResult, base.Info):
    """Blocker dependency removed more than two years ago from the tree.

    Note that this ignores slot/subslot deps and USE deps in blocker atoms.
    """

    def __init__(self, attr, atom, age, **kwargs):
        super().__init__(**kwargs)
        self.attr = attr
        self.atom = atom
        self.age = age

    @property
    def desc(self):
        return (
            f'outdated blocker {self.attr}="{self.atom}": '
            f'last match removed {self.age} years ago'
        )


class NonexistentBlocker(base.VersionedResult, base.Warning):
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


class DependencyCheck(base.Check):
    """Check BDEPEND, DEPEND, RDEPEND, and PDEPEND."""

    required_addons = (addons.UseAddon, addons.GitAddon)
    known_results = (
        MetadataError, MissingPackageRevision, MissingUseDepDefault,
        OutdatedBlocker, NonexistentBlocker, UnstatedIUSE,
    )

    feed_type = base.versioned_feed

    def __init__(self, options, iuse_handler, git_addon):
        super().__init__(options)
        self.iuse_filter = iuse_handler.get_filter()
        self.conditional_ops = {'?', '='}
        self.use_defaults = {'(+)', '(-)'}
        self.today = datetime.today()
        self._git_addon = git_addon

    @jit_attr
    def existence_repo(self):
        return self._git_addon.cached_repo(addons.GitRemovedRepo)

    @staticmethod
    def _flatten_or_restrictions(i):
        for x in i:
            if isinstance(x, boolean.OrRestriction):
                for y in iflatten_instance(x, (atom_cls,)):
                    yield (y, True)
            else:
                yield (x, False)

    def _check_use_deps(self, attr, atom):
        """Check dependencies for missing USE dep defaults."""
        conditional_use = (
            x for x in atom.use
            if (x[-1] in self.conditional_ops and x[-4:-1] not in self.use_defaults))
        stripped_use = [x.strip('?=').lstrip('!') for x in conditional_use]
        if stripped_use:
            missing_use_deps = defaultdict(set)
            for pkg in self.options.search_repo.match(atom.no_usedeps):
                for use in stripped_use:
                    if use not in pkg.iuse_effective:
                        missing_use_deps[use].add(pkg.versioned_atom)
            return missing_use_deps
        return {}

    def feed(self, pkg):
        for attr in (x.lower() for x in pkg.eapi.dep_keys):
            slot_op_or_blocks = set()
            slot_op_blockers = set()
            outdated_blockers = set()
            nonexistent_blockers = set()

            nodes, unstated = self.iuse_filter(
                (atom_cls, boolean.OrRestriction), pkg, getattr(pkg, attr), attr=attr)
            yield from unstated

            for atom, in_or_restriction in self._flatten_or_restrictions(nodes):
                if pkg.eapi.options.has_use_dep_defaults and atom.use is not None:
                    missing_use_deps = self._check_use_deps(attr, atom)
                    for use, atoms in missing_use_deps.items():
                        pkgs = map(str, sorted(atoms))
                        yield MissingUseDepDefault(attr, str(atom), use, pkgs, pkg=pkg)
                if in_or_restriction and atom.slot_operator == '=':
                    slot_op_or_blocks.add(atom.key)
                if atom.blocks:
                    if atom.match(pkg):
                        yield MetadataError(attr, "blocks itself", pkg=pkg)
                    elif atom.slot_operator == '=':
                        slot_op_blockers.add(atom.key)
                    elif self.existence_repo is not None:
                        # check for outdated blockers (2+ years old)
                        if atom.op == '=*':
                            s = f"={atom.cpvstr}*"
                        else:
                            s = atom.op + atom.cpvstr
                        unblocked = atom_cls(s)
                        if not self.options.search_repo.match(unblocked):
                            matches = self.existence_repo.match(unblocked)
                            if matches:
                                removal = max(x.date for x in matches)
                                removal = datetime.strptime(removal, '%Y-%m-%d')
                                years = round((self.today - removal).days / 365, 2)
                                if years > 2:
                                    outdated_blockers.add((atom, years))
                            else:
                                nonexistent_blockers.add((atom))
                if atom.op == '=' and not atom.revision:
                    yield MissingPackageRevision(attr, str(atom), pkg=pkg)

            if slot_op_or_blocks:
                atoms = ', '.join(sorted(slot_op_or_blocks))
                yield MetadataError(
                    attr,
                    f'= slot operator used inside || block: [{atoms}]',
                    pkg=pkg)
            if slot_op_blockers:
                atoms = ', '.join(sorted(slot_op_blockers))
                yield MetadataError(
                    attr,
                    f'= slot operator used in blocker: [{atoms}]',
                    pkg=pkg)

            for atom, years in sorted(outdated_blockers):
                yield OutdatedBlocker(attr.upper(), str(atom), years, pkg=pkg)
            for atom in sorted(nonexistent_blockers):
                yield NonexistentBlocker(attr.upper(), str(atom), pkg=pkg)


class StupidKeywords(base.VersionedResult, base.Warning):
    """Packages using ``-*``; use package.mask instead."""

    desc = "keywords contain -*; use package.mask or empty keywords instead"


class InvalidKeywords(base.VersionedResult, base.Error):
    """Packages using invalid KEYWORDS."""

    def __init__(self, keywords, **kwargs):
        super().__init__(**kwargs)
        self.keywords = tuple(keywords)

    @property
    def desc(self):
        return f"invalid KEYWORDS: {', '.join(map(repr, self.keywords))}"


class OverlappingKeywords(base.VersionedResult, base.Warning):
    """Packages having overlapping arch and ~arch KEYWORDS."""

    def __init__(self, keywords, **kwargs):
        super().__init__(**kwargs)
        self.keywords = keywords

    @property
    def desc(self):
        return f"overlapping KEYWORDS: {self.keywords}"


class DuplicateKeywords(base.VersionedResult, base.Warning):
    """Packages having duplicate KEYWORDS."""

    def __init__(self, keywords, **kwargs):
        super().__init__(**kwargs)
        self.keywords = tuple(keywords)

    @property
    def desc(self):
        return f"duplicate KEYWORDS: {', '.join(self.keywords)}"


class UnsortedKeywords(base.VersionedResult, base.Warning):
    """Packages with unsorted KEYWORDS.

    KEYWORDS should be sorted in alphabetical order with prefix keywords (those
    with hyphens in them, e.g. amd64-fbsd) after regular arches and globs (e.g. ``-*``)
    before them.
    """

    def __init__(self, keywords, sorted_keywords, **kwargs):
        super().__init__(**kwargs)
        self.keywords = tuple(keywords)
        self.sorted_keywords = tuple(sorted_keywords)

    @property
    def desc(self):
        return (
            f"\n\tunsorted KEYWORDS: {', '.join(self.keywords)}"
            f"\n\tsorted KEYWORDS: {', '.join(self.sorted_keywords)}"
        )


class MissingVirtualKeywords(base.VersionedResult, base.Warning):
    """Virtual packages with keywords missing from their dependencies."""

    def __init__(self, keywords, **kwargs):
        super().__init__(**kwargs)
        self.keywords = tuple(keywords)

    @property
    def desc(self):
        return f"missing KEYWORDS: {', '.join(self.keywords)}"


class KeywordsCheck(base.Check):
    """Check package keywords for sanity; empty keywords, and -* are flagged."""

    required_addons = (addons.UseAddon,)
    feed_type = base.versioned_feed
    known_results = (
        StupidKeywords, InvalidKeywords, OverlappingKeywords, DuplicateKeywords,
        UnsortedKeywords, MissingVirtualKeywords, MetadataError,
    )

    def __init__(self, options, iuse_handler):
        super().__init__(options)
        self.iuse_filter = iuse_handler.get_filter()
        self.valid_arches = self.options.target_repo.known_arches
        special_keywords = set(['-*'])
        stable_keywords = self.valid_arches
        unstable_keywords = set('~' + x for x in self.valid_arches)
        disabled_keywords = set('-' + x for x in self.valid_arches)
        self.valid_keywords = (
            special_keywords | stable_keywords | unstable_keywords | disabled_keywords)

        # Note: '*' and '~*' are portage-only special KEYWORDS atm, i.e. not
        # specified in PMS, so they don't belong in the main tree.
        self.portage_keywords = set(['*', '~*'])

    def feed(self, pkg):
        if len(pkg.keywords) == 1 and pkg.keywords[0] == "-*":
            yield StupidKeywords(pkg)
        else:
            # check for invalid keywords
            invalid = set(pkg.keywords) - self.valid_keywords
            # portage-only KEYWORDS are allowed in overlays
            if not self.options.gentoo_repo:
                invalid -= self.portage_keywords
            if invalid:
                yield InvalidKeywords(sorted(invalid), pkg=pkg)

            # check for overlapping keywords
            unstable = {x[1:] for x in pkg.keywords if x[0] == '~'}
            stable = {x for x in pkg.keywords if x[0] != '~'}
            overlapping = unstable & stable
            if overlapping:
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
                yield UnsortedKeywords(pkg.keywords, pkg.sorted_keywords, pkg=pkg)

            if pkg.category == 'virtual':
                keywords = set()
                rdepend, _ = self.iuse_filter((atom_cls,), pkg, pkg.rdepend)
                for x in set(rdepend):
                    for p in self.options.search_repo.match(x.no_usedeps):
                        keywords.update(
                            x for x in p.keywords if x.lstrip('~') in self.valid_arches)
                pkg_keywords = set(pkg.keywords)
                pkg_keywords.update(f'~{x}' for x in pkg.keywords if x[0] != '~')
                missing_keywords = keywords - pkg_keywords
                if missing_keywords:
                    yield MissingVirtualKeywords(sort_keywords(missing_keywords), pkg=pkg)


class MissingUri(base.VersionedResult, base.Warning):
    """RESTRICT=fetch isn't set, yet no full URI exists."""

    def __init__(self, filenames, **kwargs):
        super().__init__(**kwargs)
        self.filenames = tuple(filenames)

    @property
    def desc(self):
        filenames = ', '.join(map(repr, self.filenames))
        return f'unfetchable file{_pl(self.filenames)}: {filenames}'


class UnknownMirror(base.VersionedResult, base.Error):
    """URI uses an unknown mirror."""

    def __init__(self, filename, uri, mirror, **kwargs):
        super().__init__(**kwargs)
        self.filename = filename
        self.uri = uri
        self.mirror = mirror

    @property
    def desc(self):
        return f"file {self.filename}: unknown mirror {self.mirror!r} from URI {self.uri!r}"


class BadProtocol(base.VersionedResult, base.Warning):
    """URI uses an unsupported protocol.

    Valid protocols are currently: http, https, and ftp
    """

    def __init__(self, filename, bad_uris, **kwargs):
        super().__init__(**kwargs)
        self.filename = filename
        self.bad_uris = tuple(bad_uris)

    @property
    def desc(self):
        uris = ', '.join(map(repr, self.bad_uris))
        return f'file {self.filename!r}: bad protocol/uri{_pl(self.bad_uris)}: {uris}'


class BadFilename(base.VersionedResult, base.Warning):
    """URI uses unspecific or poor filename(s).

    Archive filenames should be disambiguated using ``->`` to rename them.
    """

    def __init__(self, filenames, **kwargs):
        super().__init__(**kwargs)
        self.filenames = tuple(filenames)

    @property
    def desc(self):
        filenames = ', '.join(self.filenames)
        return f'bad filename{_pl(self.filenames)}: [ {filenames} ]'


class TarballAvailable(base.VersionedResult, base.Warning):
    """URI uses .zip archive when .tar* is available.

    Tarballs should be preferred over zip archives due to better compression
    and no extra unpack dependencies.
    """

    def __init__(self, uris, **kwargs):
        super().__init__(**kwargs)
        self.uris = tuple(uris)

    @property
    def desc(self):
        return (f"zip archive{_pl(self.uris)} used when tarball available: "
                f"[ {' '.join(self.uris)} ]")


class SrcUriCheck(base.Check):
    """SRC_URI related checks.

    Verify that URIs are valid, fetchable, using a supported protocol, and
    don't use unspecific filenames.
    """

    required_addons = (addons.UseAddon,)
    feed_type = base.versioned_feed
    known_results = (
        BadFilename, BadProtocol, MissingUri, MetadataError, TarballAvailable,
        UnknownMirror, UnstatedIUSE,
    )

    valid_protos = frozenset(["http", "https", "ftp"])

    def __init__(self, options, iuse_handler):
        super().__init__(options)
        self.iuse_filter = iuse_handler.get_filter('fetchables')
        self.zip_to_tar_re = re.compile(
            r'https?://(github\.com/.*?/.*?/archive/.+\.zip|'
            r'gitlab\.com/.*?/.*?/-/archive/.+\.zip)')

    def feed(self, pkg):
        lacks_uri = set()
        # duplicate entries are possible.
        seen = set()
        bad_filenames = set()
        tarball_available = set()
        fetchables, unstated = self.iuse_filter(
            (fetchable,), pkg,
            pkg._get_attr['fetchables'](
                pkg, allow_missing_checksums=True,
                ignore_unknown_mirrors=True, skip_default_mirrors=True))
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
                yield UnknownMirror(f_inst.filename, uri, mirror.mirror_name, pkg=pkg)

            # Check for unspecific filenames of the form ${PN}.ext, ${PV}.ext,
            # and v${PV}.ext as well as archives named using only the raw git
            # commit hash.
            PN = re.escape(pkg.PN)
            PV = re.escape(pkg.PV)
            exts = pkg.eapi.archive_suffixes_re.pattern
            bad_filenames_re = rf'^({PN}|v?{PV}|[0-9a-f]{{40}}){exts}'
            if re.match(bad_filenames_re, f_inst.filename):
                bad_filenames.add(f_inst.filename)

            restricts = frozenset(chain.from_iterable(
                x.vals for x in restrictions if not x.negate))
            if not f_inst.uri and 'fetch' not in pkg.restrict.evaluate_depset(restricts):
                lacks_uri.add(f_inst.filename)
            else:
                bad = set()
                for x in f_inst.uri:
                    i = x.find("://")
                    if i == -1:
                        lacks_uri.add(x)
                    elif x[:i] not in self.valid_protos:
                        bad.add(x)
                    elif self.zip_to_tar_re.match(x):
                        tarball_available.add(x)
                if bad:
                    yield BadProtocol(f_inst.filename, sorted(bad), pkg=pkg)

        if lacks_uri:
            yield MissingUri(sorted(lacks_uri), pkg=pkg)
        if bad_filenames:
            yield BadFilename(sorted(bad_filenames), pkg=pkg)
        if tarball_available:
            yield TarballAvailable(sorted(tarball_available), pkg=pkg)


class BadDescription(base.VersionedResult, base.Warning):
    """Package's description is bad for some reason."""

    def __init__(self, msg, **kwargs):
        super().__init__(**kwargs)
        self.msg = msg

    @property
    def desc(self):
        return f"bad DESCRIPTION: {self.msg}"


class DescriptionCheck(base.Check):
    """DESCRIPTION checks.

    Check on length (<=150), too short (<10), or generic (lifted from eclass or
    just using the package's name.
    """

    feed_type = base.versioned_feed
    known_results = (BadDescription,)

    def feed(self, pkg):
        s = pkg.description.lower()
        if s.startswith("based on") and "eclass" in s:
            yield BadDescription("generic eclass defined description", pkg=pkg)
        elif s in (pkg.package, pkg.key):
            yield BadDescription(
                "using the pkg name as the description isn't very helpful", pkg=pkg)
        else:
            l = len(pkg.description)
            if not l:
                yield BadDescription("empty/unset", pkg=pkg)
            elif l > 150:
                yield BadDescription("over 150 chars in length, bit long", pkg=pkg)
            elif l < 10:
                yield BadDescription(
                    f"{pkg.description!r} under 10 chars in length- too short", pkg=pkg)


class BadHomepage(base.VersionedResult, base.Warning):
    """Package's homepage is bad for some reason."""

    def __init__(self, msg, **kwargs):
        super().__init__(**kwargs)
        self.msg = msg

    @property
    def desc(self):
        return f"bad HOMEPAGE: {self.msg}"


class HomepageCheck(base.Check):
    """HOMEPAGE checks."""

    feed_type = base.versioned_feed
    known_results = (BadHomepage,)

    # categories for ebuilds that should lack HOMEPAGE
    missing_categories = frozenset(['virtual', 'acct-group', 'acct-user'])

    def feed(self, pkg):
        if not pkg.homepage:
            if pkg.category not in self.missing_categories:
                yield BadHomepage("empty/unset", pkg=pkg)
        else:
            if pkg.category in self.missing_categories:
                yield BadHomepage(
                    f"{pkg.category!r} packages shouldn't define HOMEPAGE", pkg=pkg)
            else:
                for homepage in pkg.homepage:
                    i = homepage.find("://")
                    if i == -1:
                        yield BadHomepage(f"HOMEPAGE={homepage!r} lacks protocol", pkg=pkg)
                    elif homepage[:i] not in SrcUriCheck.valid_protos:
                        yield BadHomepage(
                            f"HOMEPAGE={homepage!r} uses unsupported "
                            f"protocol {homepage[:i]!r}",
                            pkg=pkg)


class BadRestricts(base.VersionedResult, base.Warning):
    """Package's RESTRICT metadata has unknown entries."""

    def __init__(self, restricts, **kwargs):
        super().__init__(**kwargs)
        self.restricts = tuple(restricts)

    @property
    def desc(self):
        restricts = ' '.join(self.restricts)
        return f'unknown RESTRICT="{restricts}"'


class UnknownProperties(base.VersionedResult, base.Warning):
    """Package's PROPERTIES metadata has unknown entries."""

    def __init__(self, properties, **kwargs):
        super().__init__(**kwargs)
        self.properties = tuple(properties)

    @property
    def desc(self):
        properties = ' '.join(self.properties)
        return f'unknown PROPERTIES="{properties}"'


class RestrictsCheck(base.Check):
    """Check for valid RESTRICT settings."""

    feed_type = base.versioned_feed
    known_results = (BadRestricts, UnknownProperties, UnstatedIUSE)
    required_addons = (addons.UseAddon,)

    def __init__(self, options, iuse_handler):
        super().__init__(options)
        self.restrict_filter = iuse_handler.get_filter('restrict')
        self.properties_filter = iuse_handler.get_filter('properties')

        # pull allowed RESTRICT/PROPERTIES values from a repo and its masters
        allowed_restricts = []
        allowed_properties = []
        for repo in options.target_repo.trees:
            allowed_restricts.extend(repo.config.restrict_allowed)
            allowed_properties.extend(repo.config.properties_allowed)
        self.allowed_restricts = frozenset(allowed_restricts)
        self.allowed_properties = frozenset(allowed_properties)

    def feed(self, pkg):
        restricts, unstated = self.restrict_filter((str,), pkg, pkg.restrict)
        yield from unstated
        properties, unstated = self.properties_filter((str,), pkg, pkg.properties)
        yield from unstated

        # skip if target repo or its masters don't define allowed values
        if self.allowed_restricts:
            bad = set(restricts).difference(self.allowed_restricts)
            if bad:
                yield BadRestricts(sorted(bad), pkg=pkg)
        if self.allowed_properties:
            unknown = set(properties).difference(self.allowed_properties)
            if unknown:
                yield UnknownProperties(sorted(unknown), pkg=pkg)


class MissingConditionalTestRestrict(base.VersionedResult, base.Warning):
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


class ConditionalTestRestrictCheck(base.Check):
    """Check whether packages specify RESTRICT="!test? ( test )"."""

    feed_type = base.versioned_feed
    known_results = (MissingConditionalTestRestrict,)

    def feed(self, pkg):
        if 'test' not in pkg.iuse:
            return

        # if the package has unconditional restriction, additional conditional
        # is unnecessary
        if 'test' in pkg.restrict:
            return

        # otherwise, it should have top-level "!test? ( test )"
        if any(isinstance(r, packages.Conditional) and r.restriction.vals == {'test'} and
               r.restriction.negate and 'test' in r.payload for r in pkg.restrict):
            return

        yield MissingConditionalTestRestrict(pkg=pkg)


class MissingUnpackerDep(base.VersionedResult, base.Warning):
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

        return (
            f'missing {dep_type}="{dep}" '
            f"for SRC_URI archive{_pl(self.filenames)}: "
            f"[ {', '.join(self.filenames)} ]"
        )


class MissingUnpackerDepCheck(base.Check):
    """Check whether package is missing unpacker dependencies."""

    feed_type = base.versioned_feed

    known_results = (MissingUnpackerDep,)
    required_addons = (addons.UseAddon,)

    non_system_unpackers = ImmutableDict({
        '.zip': frozenset(['app-arch/unzip']),
        '.7z': frozenset(['app-arch/p7zip']),
        '.rar': frozenset(['app-arch/rar', 'app-arch/unrar']),
        '.lha': frozenset(['app-arch/lha']),
        '.lzh': frozenset(['app-arch/lha']),
    })

    def __init__(self, options, iuse_handler):
        super().__init__(options)
        self.dep_filter = iuse_handler.get_filter()
        self.fetch_filter = iuse_handler.get_filter('fetchables')

    def feed(self, pkg):
        # ignore conditionals
        fetchables, _ = self.fetch_filter(
            (fetchable,), pkg,
            pkg._get_attr['fetchables'](
                pkg, allow_missing_checksums=True,
                ignore_unknown_mirrors=True, skip_default_mirrors=True))

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
