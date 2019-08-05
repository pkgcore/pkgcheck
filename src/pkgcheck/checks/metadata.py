from collections import defaultdict
from datetime import datetime
from difflib import SequenceMatcher
from operator import attrgetter
import os
import re

from pkgcore.ebuild import eapi
from pkgcore.ebuild.atom import atom as atom_cls
from pkgcore.ebuild.misc import sort_keywords
from pkgcore.fetch import fetchable, unknown_mirror
from pkgcore.restrictions.boolean import OrRestriction
from snakeoil.demandload import demandload
from snakeoil.mappings import ImmutableDict
from snakeoil.osutils import listdir_files
from snakeoil.sequences import iflatten_instance
from snakeoil.strings import pluralism as _pl

from .. import base, addons
from ..base import MetadataError
from .visibility import FakeConfigurable, strip_atom_use


class MissingLicense(base.Error):
    """Used license(s) have no matching license file(s)."""

    __slots__ = ("category", "package", "version", "licenses")
    threshold = base.versioned_feed

    def __init__(self, pkg, licenses):
        super().__init__()
        self._store_cpv(pkg)
        self.licenses = tuple(sorted(licenses))

    @property
    def short_desc(self):
        licenses = ', '.join(self.licenses)
        return f"no matching license{_pl(self.licenses)}: [ {licenses} ]"


class UnnecessaryLicense(base.Warning):
    """LICENSE defined for package that is license-less."""

    __slots__ = ("category", "package", "version")
    threshold = base.versioned_feed

    def __init__(self, pkg):
        super().__init__()
        self._store_cpv(pkg)

    @property
    def short_desc(self):
        return f"{self.category!r} packages shouldn't define LICENSE"


class LicenseMetadataCheck(base.Template):
    """LICENSE validity checks."""

    known_results = (MetadataError, MissingLicense, UnnecessaryLicense, addons.UnstatedIUSE)
    feed_type = base.versioned_feed

    # categories for ebuilds that can lack LICENSE settings
    unlicensed_categories = frozenset(['virtual', 'acct-group', 'acct-user'])

    required_addons = (addons.UseAddon, addons.ProfileAddon)

    def __init__(self, options, iuse_handler, profiles):
        super().__init__(options)
        self.iuse_filter = iuse_handler.get_filter('license')

    def feed(self, pkg):
        licenses, unstated = self.iuse_filter((str,), pkg, pkg.license)
        yield from unstated

        licenses = set(licenses)
        if not licenses:
            if pkg.category not in self.unlicensed_categories:
                yield MetadataError(pkg, "license", "no license defined")
        else:
            licenses.difference_update(pkg.repo.licenses)
            if licenses:
                yield MissingLicense(pkg, licenses)
            elif pkg.category in self.unlicensed_categories:
                yield UnnecessaryLicense(pkg)


class IUSEMetadataCheck(base.Template):
    """IUSE validity checks."""

    feed_type = base.versioned_feed
    required_addons = (addons.UseAddon,)
    known_results = (MetadataError, addons.UnstatedIUSE)

    def __init__(self, options, iuse_handler):
        super().__init__(options)
        self.iuse_handler = iuse_handler

    def feed(self, pkg):
        if not self.iuse_handler.ignore:
            iuse = pkg.iuse_stripped.difference(self.iuse_handler.allowed_iuse(pkg))
            if iuse:
                yield MetadataError(
                    pkg, "iuse", "IUSE unknown flag%s: [ %s ]" % (
                        _pl(iuse), ", ".join(sorted(iuse))))


class DeprecatedEAPI(base.Warning):
    """Package's EAPI is deprecated according to repo metadata."""

    __slots__ = ("category", "package", "version", "eapi")
    threshold = base.versioned_feed

    def __init__(self, pkg):
        super().__init__()
        self._store_cpv(pkg)
        self.eapi = str(pkg.eapi)

    @property
    def short_desc(self):
        return f"uses deprecated EAPI {self.eapi}"


class BannedEAPI(base.Error):
    """Package's EAPI is banned according to repo metadata."""

    __slots__ = ("category", "package", "version", "eapi")
    threshold = base.versioned_feed

    def __init__(self, pkg):
        super().__init__()
        self._store_cpv(pkg)
        self.eapi = str(pkg.eapi)

    @property
    def short_desc(self):
        return f"uses banned EAPI {self.eapi}"


class MetadataCheck(base.Template):
    """Scan for packages with banned/deprecated EAPIs or bad metadata."""

    feed_type = base.versioned_feed
    known_results = (DeprecatedEAPI, BannedEAPI)

    def feed(self, pkg):
        eapi_str = str(pkg.eapi)
        if eapi_str in pkg.repo.config.eapis_banned:
            yield BannedEAPI(pkg)
        elif eapi_str in pkg.repo.config.eapis_deprecated:
            yield DeprecatedEAPI(pkg)

    def finish(self):
        # report all masked pkgs due to invalid EAPIs and other bad metadata
        for pkg in self.options.target_repo._masked:
            e = pkg.data
            yield MetadataError(
                pkg.versioned_atom, e.attr, e.msg(verbosity=self.options.verbosity))


class RequiredUseDefaults(base.Warning):
    """Default USE flag settings don't satisfy REQUIRED_USE.

    The REQUIRED_USE constraints specified in the ebuild are not satisfied
    by the default USE flags used in one or more profiles. This means that
    users on those profiles may be unable to install the package out of the box,
    without having to modify package.use.

    This warning is usually fixed via using IUSE defaults to enable one
    of the needed flags, modifying package.use in the most relevant profiles
    or modifying REQUIRED_USE.
    """

    __slots__ = (
        "category", "package", "version", "profile", "num_profiles", "keyword",
        "required_use", "use",
    )
    threshold = base.versioned_feed

    def __init__(self, pkg, required_use, use=(), keyword=None,
                 profile=None, num_profiles=None):
        super().__init__()
        self._store_cpv(pkg)
        self.required_use = str(required_use)
        self.use = tuple(sorted(use))
        self.keyword = keyword
        self.profile = profile
        self.num_profiles = num_profiles

    @property
    def short_desc(self):
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
        else:
            return (
                f'keyword: {self.keyword}, profile: {self.profile!r}, '
                f"default USE: [{', '.join(self.use)}] "
                f'-- failed REQUIRED_USE: {self.required_use}'
            )


class RequiredUSEMetadataCheck(base.Template):
    """REQUIRED_USE validity checks."""

    feed_type = base.versioned_feed
    required_addons = (addons.UseAddon, addons.ProfileAddon)
    known_results = (MetadataError, RequiredUseDefaults, addons.UnstatedIUSE)

    def __init__(self, options, iuse_handler, profiles):
        super().__init__(options)
        self.iuse_filter = iuse_handler.get_filter('required_use')
        self.profiles = profiles

    def feed(self, pkg):
        # only run the check for EAPI 4 and above
        if not pkg.eapi.options.has_required_use:
            return

        # check REQUIRED_USE for invalid nodes
        nodes, unstated = self.iuse_filter((str,), pkg, pkg.required_use)
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
                    yield RequiredUseDefaults(pkg, node, use, keyword, profile)
        else:
            # only report one failure per REQUIRED_USE node in regular mode
            for node, profile_info in failures.items():
                num_profiles = len(profile_info)
                _use, _keyword, profile = profile_info[0]
                yield RequiredUseDefaults(
                    pkg, node, profile=profile, num_profiles=num_profiles)


class UnusedLocalUSE(base.Warning):
    """Unused local USE flag(s)."""

    __slots__ = ("category", "package", "flags")

    threshold = base.package_feed

    def __init__(self, pkg, flags):
        super().__init__()
        self._store_cp(pkg)
        self.flags = tuple(sorted(flags))

    @property
    def short_desc(self):
        return "metadata.xml unused local USE flag%s: [ %s ]" % (
            _pl(self.flags), ', '.join(self.flags))


class MatchingGlobalUSE(base.Error):
    """Local USE flag description matches a global USE flag."""

    __slots__ = ("category", "package", "flag")
    threshold = base.package_feed

    def __init__(self, pkg, flag):
        super().__init__()
        self._store_cp(pkg)
        self.flag = flag

    @property
    def short_desc(self):
        return f"local USE flag matches a global: {self.flag!r}"


class ProbableGlobalUSE(base.Warning):
    """Local USE flag description closely matches a global USE flag."""

    __slots__ = ("category", "package", "flag")
    threshold = base.package_feed

    def __init__(self, pkg, flag):
        super().__init__()
        self._store_cp(pkg)
        self.flag = flag

    @property
    def short_desc(self):
        return f"local USE flag closely matches a global: {self.flag!r}"


class ProbableUseExpand(base.Warning):
    """Local USE flag that isn't overridden matches a USE_EXPAND group.

    The local USE flag starts with a prefix reserved to USE_EXPAND group,
    yet it is not a globally defined member of this group. According
    to the standing policy [#]_, all possible values for each USE_EXPAND
    must be defined and documented globally.

    This warning can be fixed via moving the local flag description
    into appropriate profiles/desc file.

    .. [#] https://devmanual.gentoo.org/general-concepts/use-flags/
    """

    __slots__ = ("category", "package", "flag", "group")
    threshold = base.package_feed

    def __init__(self, pkg, flag, group):
        super().__init__()
        self._store_cp(pkg)
        self.flag = flag
        self.group = group

    @property
    def short_desc(self):
        return f"USE_EXPAND group {self.group!r} matches local USE flag: {self.flag!r}"


class LocalUSECheck(base.Template):
    """Check local USE flags in metadata.xml for various issues."""

    feed_type = base.package_feed
    required_addons = (addons.UseAddon,)
    known_results = (
        UnusedLocalUSE, MatchingGlobalUSE, ProbableGlobalUSE,
        ProbableUseExpand, addons.UnstatedIUSE,
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
                    yield MatchingGlobalUSE(pkg, flag)
                elif ratio >= 0.75:
                    yield ProbableGlobalUSE(pkg, flag)
            else:
                for group in self.use_expand_groups:
                    if (flag.startswith(f'{group}_') and
                            flag not in self.use_expand_groups[group]):
                        yield ProbableUseExpand(pkg, flag, group.upper())
                        break

        unused = set(local_use)
        for pkg in pkgs:
            unused.difference_update(pkg.iuse_stripped)
        if unused:
            yield UnusedLocalUSE(pkg, unused)


class MissingSlotDep(base.Warning):
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

    __slots__ = ('category', 'package', 'version', 'dep', 'dep_slots')

    threshold = base.versioned_feed

    def __init__(self, pkg, dep, dep_slots):
        super().__init__()
        self.dep = dep
        self.dep_slots = tuple(sorted(dep_slots))
        self._store_cpv(pkg)

    @property
    def short_desc(self):
        return (
            f"{self.dep!r} matches more than one slot: "
            f"[ {', '.join(self.dep_slots)} ]")


class MissingSlotDepCheck(base.Template):
    """Check for missing slot dependencies."""

    feed_type = base.versioned_feed
    required_addons = (addons.UseAddon,)
    known_results = (MissingSlotDep,)

    def __init__(self, options, iuse_handler):
        super().__init__(options)
        self.iuse_filter = iuse_handler.get_filter()

    def feed(self, pkg):
        # only run the check for EAPI 5 and above
        if not pkg.eapi.options.sub_slotting:
            return

        rdepend, _ = self.iuse_filter((atom_cls,), pkg, pkg.rdepend)
        depend, _ = self.iuse_filter((atom_cls,), pkg, pkg.depend)

        # skip deps that are blockers or have explicit slots/slot operators
        for dep in (x for x in set(rdepend).intersection(depend) if not
                    (x.blocks or x.slot is not None or x.slot_operator is not None)):
            dep_slots = set(x.slot for x in pkg.repo.itermatch(dep))
            if len(dep_slots) > 1:
                yield MissingSlotDep(pkg, str(dep), dep_slots)


class MissingPackageRevision(base.Warning):
    """Missing package revision in =cat/pkg dependencies.

    The dependency string uses the ``=`` operator without specifying a revision.
    This means that only ``-r0`` of the dependency will be matched, and newer
    revisions of the same ebuild will not be accepted.

    If any revision of the package is acceptable, the ``~`` operator should be
    used instead of ``=``. If only the initial revision of the dependency is
    allowed, ``-r0`` should be appended in order to make the intent explicit.
    """

    __slots__ = ('category', 'package', 'version', 'dep', 'atom')

    threshold = base.versioned_feed

    def __init__(self, pkg, dep, atom):
        super().__init__()
        self._store_cpv(pkg)
        self.dep = dep.upper()
        self.atom = str(atom)

    @property
    def short_desc(self):
        return f'{self.dep}="{self.atom}": "=" operator used without package revision'


class MissingUseDepDefault(base.Warning):
    """Package dependencies with USE dependencies missing defaults."""

    __slots__ = ('category', 'package', 'version', 'attr', 'atom', 'flag', 'pkg_deps')

    threshold = base.versioned_feed

    def __init__(self, pkg, attr, atom, flag, pkg_deps):
        super().__init__()
        self._store_cpv(pkg)
        self.attr = attr.upper()
        self.atom = str(atom)
        self.pkg_deps = tuple(sorted(str(x.versioned_atom) for x in pkg_deps))
        self.flag = flag

    @property
    def short_desc(self):
        return (
            f'{self.attr}="{self.atom}": USE flag {self.flag!r} missing from '
            f"package{_pl(self.pkg_deps)}: [ {', '.join(self.pkg_deps)} ]")


class OutdatedBlocker(base.Warning):
    """Blocker dependency removed more than two years ago from the tree.

    Note that this ignores slot/subslot deps and USE deps in blocker atoms.
    """

    __slots__ = ("category", "package", "version", "attr", "atom", "age")

    threshold = base.versioned_feed

    def __init__(self, pkg, attr, atom, age):
        super().__init__()
        self._store_cpv(pkg)
        self.attr = attr.upper()
        self.atom = str(atom)
        self.age = age

    @property
    def short_desc(self):
        return (
            f'outdated blocker {self.attr}="{self.atom}": '
            f'last match removed {self.age} years ago'
        )


class NonexistentBlocker(base.Warning):
    """No matches for blocker dependency in repo history.

    For the gentoo repo this means it was either removed before the CVS -> git
    transition (which occurred around 2015-08-08) or it never existed at all.

    Note that this ignores slot/subslot deps and USE deps in blocker atoms.
    """

    __slots__ = ("category", "package", "version", "attr", "atom")

    threshold = base.versioned_feed

    def __init__(self, pkg, attr, atom):
        super().__init__()
        self._store_cpv(pkg)
        self.attr = attr.upper()
        self.atom = str(atom)

    @property
    def short_desc(self):
        return (
            f'nonexistent blocker {self.attr}="{self.atom}": '
            'no matches in repo history'
        )


class DependencyCheck(base.Template):
    """Check BDEPEND, DEPEND, RDEPEND, and PDEPEND."""

    required_addons = (addons.UseAddon, addons.GitAddon)
    known_results = (
        MetadataError, MissingPackageRevision, MissingUseDepDefault,
        OutdatedBlocker, NonexistentBlocker, addons.UnstatedIUSE,
    )

    feed_type = base.versioned_feed

    attrs = tuple((x, attrgetter(x)) for x in
                  ("bdepend", "depend", "rdepend", "pdepend"))

    def __init__(self, options, iuse_handler, git_addon):
        super().__init__(options)
        self.iuse_filter = iuse_handler.get_filter()
        self.conditional_ops = {'?', '='}
        self.use_defaults = {'(+)', '(-)'}
        self.today = datetime.today()
        self.existence_repo = git_addon.cached_repo(addons.GitRemovedRepo)

    @staticmethod
    def _flatten_or_restrictions(i):
        for x in i:
            if isinstance(x, OrRestriction):
                for y in iflatten_instance(x, (atom_cls,)):
                    yield (y, True)
            else:
                yield (x, False)

    def _check_use_deps(self, attr, pkg, atom):
        """Check dependencies for missing USE dep defaults."""
        conditional_use = (
            x for x in atom.use
            if (x[-1] in self.conditional_ops and x[-4:-1] not in self.use_defaults))
        stripped_use = [x.strip('?=').lstrip('!') for x in conditional_use]
        if stripped_use:
            missing_use_deps = defaultdict(set)
            for pkg_dep in self.options.search_repo.match(strip_atom_use(atom)):
                for use in stripped_use:
                    if use not in pkg_dep.iuse_effective:
                        missing_use_deps[use].add(pkg_dep)
            return missing_use_deps
        return {}

    def feed(self, pkg):
        for attr_name, getter in self.attrs:
            slot_op_or_blocks = set()
            slot_op_blockers = set()
            outdated_blockers = set()
            nonexistent_blockers = set()

            nodes, unstated = self.iuse_filter(
                (atom_cls, OrRestriction), pkg, getter(pkg), attr=attr_name)
            yield from unstated

            for atom, in_or_restriction in self._flatten_or_restrictions(nodes):
                if pkg.eapi.options.has_use_dep_defaults and atom.use is not None:
                    missing_use_deps = self._check_use_deps(attr_name, pkg, atom)
                    for use, pkg_deps in missing_use_deps.items():
                        yield MissingUseDepDefault(pkg, attr_name, atom, use, pkg_deps)
                if in_or_restriction and atom.slot_operator == '=':
                    slot_op_or_blocks.add(atom.key)
                if atom.blocks:
                    if atom.match(pkg):
                        yield MetadataError(pkg, attr_name, "blocks itself")
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
                                    outdated_blockers.add((attr_name, atom, years))
                            else:
                                nonexistent_blockers.add((attr_name, atom))
                if atom.op == '=' and not atom.revision:
                    yield MissingPackageRevision(pkg, attr_name, atom)

            if slot_op_or_blocks:
                yield MetadataError(
                    pkg, attr_name,
                    "= slot operator used inside || block: [%s]" %
                    (', '.join(sorted(slot_op_or_blocks),)))
            if slot_op_blockers:
                yield MetadataError(
                    pkg, attr_name,
                    "= slot operator used in blocker: [%s]" %
                    (', '.join(sorted(slot_op_blockers),)))

            for attr, atom, years in sorted(outdated_blockers):
                yield OutdatedBlocker(pkg, attr, atom, years)
            for attr, atom in sorted(nonexistent_blockers):
                yield NonexistentBlocker(pkg, attr, atom)


class StupidKeywords(base.Warning):
    """Packages using ``-*``; use package.mask instead."""

    __slots__ = ('category', 'package', 'version')
    threshold = base.versioned_feed

    def __init__(self, pkg):
        super().__init__()
        self._store_cpv(pkg)

    short_desc = (
        "keywords contain -*; use package.mask or empty keywords instead")


class InvalidKeywords(base.Error):
    """Packages using invalid KEYWORDS."""

    __slots__ = ('category', 'package', 'version', 'keywords')
    threshold = base.versioned_feed

    def __init__(self, pkg, keywords):
        super().__init__()
        self._store_cpv(pkg)
        self.keywords = tuple(sorted(keywords))

    @property
    def short_desc(self):
        return f"invalid KEYWORDS: {', '.join(map(repr, self.keywords))}"


class OverlappingKeywords(base.Warning):
    """Packages having overlapping arch and ~arch KEYWORDS."""

    __slots__ = ('category', 'package', 'version', 'keywords')
    threshold = base.versioned_feed

    def __init__(self, pkg, keywords):
        super().__init__()
        self._store_cpv(pkg)
        self.keywords = tuple(sorted(zip(keywords, ('~' + x for x in keywords))))

    @property
    def short_desc(self):
        return f"overlapping KEYWORDS: {', '.join(map(str, self.keywords))}"


class DuplicateKeywords(base.Warning):
    """Packages having duplicate KEYWORDS."""

    __slots__ = ('category', 'package', 'version', 'keywords')
    threshold = base.versioned_feed

    def __init__(self, pkg, keywords):
        super().__init__()
        self._store_cpv(pkg)
        self.keywords = tuple(keywords)

    @property
    def short_desc(self):
        return f"duplicate KEYWORDS: {', '.join(self.keywords)}"


class UnsortedKeywords(base.Warning):
    """Packages with unsorted KEYWORDS.

    KEYWORDS should be sorted in alphabetical order with prefix keywords (those
    with hyphens in them, e.g. amd64-fbsd) after regular arches and globs (e.g. ``-*``)
    before them.
    """

    __slots__ = ('category', 'package', 'version', 'keywords')
    threshold = base.versioned_feed

    def __init__(self, pkg):
        super().__init__()
        self._store_cpv(pkg)
        self.keywords = tuple(pkg.keywords)
        self.sorted_keywords = tuple(pkg.sorted_keywords)

    @property
    def short_desc(self):
        return f"unsorted KEYWORDS: {', '.join(self.keywords)}"

    @property
    def long_desc(self):
        return (
            f"\n\tunsorted: {', '.join(self.keywords)}"
            f"\n\tsorted: {', '.join(self.sorted_keywords)}")


class MissingVirtualKeywords(base.Warning):
    """Virtual packages with keywords missing from their dependencies."""

    __slots__ = ('category', 'package', 'version', 'keywords')
    threshold = base.versioned_feed

    def __init__(self, pkg, keywords):
        super().__init__()
        self._store_cpv(pkg)
        self.keywords = tuple(sort_keywords(keywords))

    @property
    def short_desc(self):
        return f"missing KEYWORDS: {', '.join(self.keywords)}"


class KeywordsCheck(base.Template):
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
            if self.options.target_repo.repo_id != 'gentoo':
                invalid -= self.portage_keywords
            if invalid:
                yield InvalidKeywords(pkg, invalid)

            # check for overlapping keywords
            unstable = {x[1:] for x in pkg.keywords if x[0] == '~'}
            stable = {x for x in pkg.keywords if x[0] != '~'}
            overlapping = unstable & stable
            if overlapping:
                yield OverlappingKeywords(pkg, overlapping)

            # check for duplicate keywords
            duplicates = set()
            seen = set()
            for x in pkg.keywords:
                if x not in seen:
                    seen.add(x)
                else:
                    duplicates.add(x)
            if duplicates:
                yield DuplicateKeywords(pkg, duplicates)

            # check for unsorted keywords
            if pkg.sorted_keywords != pkg.keywords:
                yield UnsortedKeywords(pkg)

            if pkg.category == 'virtual':
                keywords = set()
                rdepend, _ = self.iuse_filter((atom_cls,), pkg, pkg.rdepend)
                for x in set(rdepend):
                    for p in self.options.search_repo.match(strip_atom_use(x)):
                        keywords.update(p.keywords)
                keywords = keywords | {f'~{x}' for x in keywords if x in self.valid_arches}
                missing_keywords = set(pkg.keywords) - keywords
                if missing_keywords:
                    yield MissingVirtualKeywords(pkg, missing_keywords)


class MissingUri(base.Warning):
    """RESTRICT=fetch isn't set, yet no full URI exists."""

    __slots__ = ("category", "package", "version", "filename")
    threshold = base.versioned_feed

    def __init__(self, pkg, filename):
        super().__init__()
        self._store_cpv(pkg)
        self.filename = filename

    @property
    def short_desc(self):
        return f"file {self.filename} is unfetchable- no URI available, and " \
            "RESTRICT=fetch isn't set"


class UnknownMirror(base.Error):
    """URI uses an unknown mirror."""

    __slots__ = ("category", "package", "version", "filename", "uri", "mirror")
    threshold = base.versioned_feed

    def __init__(self, pkg, filename, uri, mirror):
        super().__init__()
        self._store_cpv(pkg)
        self.filename = filename
        self.uri = uri
        self.mirror = mirror

    @property
    def short_desc(self):
        return f"file {self.filename}: unknown mirror {self.mirror!r} from URI {self.uri!r}"


class BadProto(base.Warning):
    """URI uses an unsupported protocol.

    Valid protocols are currently: http, https, and ftp
    """

    __slots__ = ("category", "package", "version", "filename", "bad_uri")
    threshold = base.versioned_feed

    def __init__(self, pkg, filename, bad_uri):
        super().__init__()
        self._store_cpv(pkg)
        self.filename = filename
        self.bad_uri = tuple(sorted(bad_uri))

    @property
    def short_desc(self):
        return f"file {self.filename}: bad protocol/uri: {self.bad_uri!r}"


class BadFilename(base.Warning):
    """URI uses unspecific or poor filename(s).

    Archive filenames should be disambiguated using ``->`` to rename them.
    """

    __slots__ = ("category", "package", "version", "filenames")
    threshold = base.versioned_feed

    def __init__(self, pkg, filenames):
        super().__init__()
        self._store_cpv(pkg)
        self.filenames = tuple(sorted(filenames))

    @property
    def short_desc(self):
        return "bad filename%s: [ %s ]" % (_pl(self.filenames), ', '.join(self.filenames))


class TarballAvailable(base.Warning):
    """URI uses .zip archive when .tar* is available.

    Tarballs should be preferred over zip archives due to better compression
    and no extra unpack dependencies.
    """

    __slots__ = ("category", "package", "version", "uris")
    threshold = base.versioned_feed

    def __init__(self, pkg, uris):
        super().__init__()
        self._store_cpv(pkg)
        self.uris = tuple(sorted(uris))

    @property
    def short_desc(self):
        return (f"zip archive{_pl(self.uris)} used when tarball available: "
                f"[ {' '.join(self.uris)} ]")


class SrcUriCheck(base.Template):
    """SRC_URI related checks.

    Verify that URIs are valid, fetchable, using a supported protocol, and
    don't use unspecific filenames.
    """

    required_addons = (addons.UseAddon,)
    feed_type = base.versioned_feed
    known_results = (
        BadFilename, BadProto, MissingUri, MetadataError, TarballAvailable,
        UnknownMirror, addons.UnstatedIUSE,
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
        for f_inst in fetchables:
            if f_inst.filename in seen:
                continue
            seen.add(f_inst.filename)

            mirrors = f_inst.uri.visit_mirrors(treat_default_as_mirror=False)
            unknown_mirrors = [
                (m, sub_uri) for m, sub_uri in mirrors if isinstance(m, unknown_mirror)]
            for mirror, sub_uri in unknown_mirrors:
                uri = f"{mirror}/{sub_uri}"
                yield UnknownMirror(pkg, f_inst.filename, uri, mirror.mirror_name)

            # Check for unspecific filenames of the form ${PV}.ext and
            # v${PV}.ext prevalent in github tagged releases as well as
            # archives named using only the raw git commit hash.
            bad_filenames_re = r'^(v?%s|[0-9a-f]{40})%s' % (
                pkg.PV, pkg.eapi.archive_suffixes_re.pattern)
            if re.match(bad_filenames_re, f_inst.filename):
                bad_filenames.add(f_inst.filename)

            if not f_inst.uri:
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
                    yield BadProto(pkg, f_inst.filename, bad)
        if "fetch" not in pkg.restrict:
            for x in sorted(lacks_uri):
                yield MissingUri(pkg, x)

        if bad_filenames:
            yield BadFilename(pkg, bad_filenames)
        if tarball_available:
            yield TarballAvailable(pkg, tarball_available)


class BadDescription(base.Warning):
    """Package's description is bad for some reason."""

    __slots__ = ("category", "package", "version", "msg")
    threshold = base.versioned_feed

    def __init__(self, pkg, msg):
        super().__init__()
        self._store_cpv(pkg)
        self.msg = msg

    @property
    def short_desc(self):
        return f"bad DESCRIPTION: {self.msg}"


class DescriptionCheck(base.Template):
    """DESCRIPTION checks.

    Check on length (<=150), too short (<10), or generic (lifted from eclass or
    just using the package's name.
    """

    feed_type = base.versioned_feed
    known_results = (BadDescription,)

    def feed(self, pkg):
        s = pkg.description.lower()
        if s.startswith("based on") and "eclass" in s:
            yield BadDescription(pkg, "generic eclass defined description")
        elif pkg.package == s or pkg.key == s:
            yield BadDescription(
                pkg, "using the pkg name as the description isn't very helpful")
        else:
            l = len(pkg.description)
            if not l:
                yield BadDescription(pkg, "empty/unset")
            elif l > 150:
                yield BadDescription(pkg, "over 150 chars in length, bit long")
            elif l < 10:
                yield BadDescription(
                    pkg, f"{pkg.description!r} under 10 chars in length- too short")


class BadHomepage(base.Warning):
    """Package's homepage is bad for some reason."""

    __slots__ = ("category", "package", "version", "msg")
    threshold = base.versioned_feed

    def __init__(self, pkg, msg):
        super().__init__()
        self._store_cpv(pkg)
        self.msg = msg

    @property
    def short_desc(self):
        return f"bad HOMEPAGE: {self.msg}"


class HomepageCheck(base.Template):
    """HOMEPAGE checks."""

    feed_type = base.versioned_feed
    known_results = (BadHomepage,)

    # categories for ebuilds that should lack HOMEPAGE
    missing_categories = frozenset(['virtual', 'acct-group', 'acct-user'])

    def feed(self, pkg):
        if not pkg.homepage:
            if pkg.category not in self.missing_categories:
                yield BadHomepage(pkg, "empty/unset")
        else:
            if pkg.category in self.missing_categories:
                yield BadHomepage(
                    pkg, f"{pkg.category!r} packages shouldn't define HOMEPAGE")
            else:
                for homepage in pkg.homepage:
                    i = homepage.find("://")
                    if i == -1:
                        yield BadHomepage(pkg, f"HOMEPAGE={homepage!r} lacks protocol")
                    elif homepage[:i] not in SrcUriCheck.valid_protos:
                        yield BadHomepage(
                            pkg,
                            f"HOMEPAGE={homepage!r} uses unsupported "
                            f"protocol {homepage[:i]!r}")


class BadRestricts(base.Warning):
    """Package's RESTRICT metadata has unknown/deprecated entries."""

    __slots__ = ("category", "package", "version", "restricts", "deprecated")
    threshold = base.versioned_feed

    def __init__(self, pkg, restricts, deprecated=None):
        super().__init__()
        self._store_cpv(pkg)
        self.restricts = restricts
        self.deprecated = deprecated
        if not restricts and not deprecated:
            raise TypeError("deprecated or restricts must not be empty")

    @property
    def short_desc(self):
        s = ''
        if self.restricts:
            s = f"unknown restricts: {', '.join(self.restricts)}"
        if self.deprecated:
            if s:
                s += "; "
            s += f"deprecated (drop the 'no') [ {', '.join(self.deprecated)} ]"
        return s


class RestrictsCheck(base.Template):
    """Check for valid RESTRICT settings."""

    feed_type = base.versioned_feed
    known_results = (BadRestricts, addons.UnstatedIUSE)
    required_addons = (addons.UseAddon,)

    def __init__(self, options, iuse_handler):
        super().__init__(options)
        self.iuse_filter = iuse_handler.get_filter('restrict')

        # pull allowed RESTRICT values from a repo and its masters
        allowed_restricts = []
        for repo in options.target_repo.trees:
            allowed_restricts.extend(options.target_repo.config.restrict_allowed)
        self.allowed_restricts = frozenset(allowed_restricts)

    def feed(self, pkg):
        # ignore conditionals
        restricts, unstated = self.iuse_filter((str,), pkg, pkg.restrict)
        yield from unstated
        bad = set(restricts).difference(self.allowed_restricts)
        if bad:
            deprecated = set(
                x for x in bad if x.startswith("no") and x[2:] in self.allowed_restricts)
            yield BadRestricts(pkg, bad.difference(deprecated), deprecated)


class MissingUnpackerDep(base.Warning):
    """Missing dependency on a required unpacker package.

    Package uses an archive format for which an unpacker is not provided by the
    system set, and lacks an explicit dependency on the unpacker package.
    """

    __slots__ = ("category", "package", "version", "eapi", "filenames", "unpackers")
    threshold = base.versioned_feed

    def __init__(self, pkg, filenames, unpackers):
        super().__init__()
        self._store_cpv(pkg)
        self.eapi = str(pkg.eapi)
        self.filenames = tuple(sorted(filenames))
        self.unpackers = tuple(sorted(map(str, unpackers)))

    @property
    def short_desc(self):
        # determine proper dep type from pkg EAPI
        eapi_obj = eapi.get_eapi(self.eapi)
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


class MissingUnpackerDepCheck(base.Template):
    """Check whether package is missing unpacker dependencies."""

    feed_type = base.versioned_feed

    known_results = (MissingUnpackerDep,)
    required_addons = (addons.UseAddon,)

    non_system_unpackers = ImmutableDict({
        '.zip': frozenset([atom_cls('app-arch/unzip')]),
        '.jar': frozenset([atom_cls('app-arch/unzip')]),
        '.7z': frozenset([atom_cls('app-arch/p7zip')]),
        '.rar': frozenset([atom_cls('app-arch/rar'), atom_cls('app-arch/unrar')]),
        '.lha': frozenset([atom_cls('app-arch/lha')]),
        '.lzh': frozenset([atom_cls('app-arch/lha')]),
    })

    def __init__(self, options, iuse_handler):
        super().__init__(options)
        self.dep_filter = iuse_handler.get_filter()
        self.fetch_filter = iuse_handler.get_filter('fetchables')

    def feed(self, pkg):
        # ignore conditionals
        fetchables, _ = self.fetch_filter((fetchable,), pkg,
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
                for unpackers in list(missing_unpackers.keys()):
                    if unpackers.intersection(deps):
                        missing_unpackers.pop(unpackers, None)

        for unpackers, filenames in missing_unpackers.items():
            yield MissingUnpackerDep(pkg, filenames, unpackers)
