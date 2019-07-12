from collections import defaultdict
from datetime import datetime
from difflib import SequenceMatcher
from operator import attrgetter
import os
import pickle
import re
import subprocess

from pkgcore.ebuild.atom import MalformedAtom, atom as atom_cls
from pkgcore.ebuild.misc import sort_keywords
from pkgcore.fetch import fetchable, unknown_mirror
from pkgcore.repository.util import SimpleTree
from pkgcore.repository import multiplex
from pkgcore.restrictions.boolean import OrRestriction
from snakeoil.cli.exceptions import UserException
from snakeoil.demandload import demandload, demand_compile_regexp
from snakeoil.osutils import pjoin, listdir_files
from snakeoil.process.spawn import spawn_get_output
from snakeoil.sequences import iflatten_instance
from snakeoil.strings import pluralism as _pl

from .. import base, addons
from ..base import MetadataError
from .visibility import FakeConfigurable, strip_atom_use

demandload('logging')
# hacky ebuild path regex for git log parsing, proper atom validation is handled later
demand_compile_regexp('ebuild_path_regex', r'^([^/]+)/([^/]+)/([^/]+)\.ebuild$')


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
        return ', '.join(self.licenses)


class LicenseMetadataReport(base.Template):
    """LICENSE validity checks."""

    known_results = (MetadataError, MissingLicense) + \
        addons.UseAddon.known_results
    feed_type = base.versioned_feed

    required_addons = (addons.UseAddon, addons.ProfileAddon)

    def __init__(self, options, iuse_handler, profiles):
        super().__init__(options)
        self.iuse_filter = iuse_handler.get_filter('license')

    def feed(self, pkg, reporter):
        licenses = set(self.iuse_filter((str,), pkg, pkg.license, reporter))
        if not licenses:
            if pkg.category != 'virtual':
                reporter.add_report(MetadataError(
                    pkg, "license", "no license defined"))
        else:
            licenses.difference_update(pkg.repo.licenses)
            if licenses:
                reporter.add_report(MissingLicense(pkg, licenses))


class IUSEMetadataReport(base.Template):
    """IUSE validity checks."""

    feed_type = base.versioned_feed
    required_addons = (addons.UseAddon,)
    known_results = (MetadataError,) + addons.UseAddon.known_results

    def __init__(self, options, iuse_handler):
        super().__init__(options)
        self.iuse_handler = iuse_handler

    def feed(self, pkg, reporter):
        if not self.iuse_handler.ignore:
            iuse = pkg.iuse_stripped.difference(self.iuse_handler.allowed_iuse(pkg))
            if iuse:
                reporter.add_report(MetadataError(
                    pkg, "iuse", "IUSE unknown flag%s: [ %s ]" % (
                        _pl(iuse), ", ".join(sorted(iuse)))))


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


class MetadataReport(base.Template):
    """Scan for packages with banned/deprecated EAPIs or bad metadata."""

    feed_type = base.versioned_feed
    known_results = (DeprecatedEAPI,)

    def feed(self, pkg, reporter):
        eapi_str = str(pkg.eapi)
        if eapi_str in pkg.repo.config.eapis_banned:
            reporter.add_report(BannedEAPI(pkg))
        elif eapi_str in pkg.repo.config.eapis_deprecated:
            reporter.add_report(DeprecatedEAPI(pkg))

    def finish(self, reporter):
        # report all masked pkgs due to invalid EAPIs and other bad metadata
        for pkg in self.options.target_repo._masked:
            e = pkg.data
            reporter.add_report(MetadataError(
                pkg.versioned_atom, e.attr, e.msg(verbosity=reporter.verbosity)))


class RequiredUseDefaults(base.Warning):
    """Default USE flag settings don't satisfy REQUIRED_USE."""

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
            # collapsed version
            return (
                f'profile: {self.profile!r} ({self.num_profiles} total) '
                f'failed REQUIRED_USE: {self.required_use}'
            )
        else:
            return (
                f'keyword: {self.keyword}, profile: {self.profile}, '
                f"default USE: [{', '.join(self.use)}] "
                f'-- failed REQUIRED_USE: {self.required_use}'
            )


class RequiredUSEMetadataReport(base.Template):
    """REQUIRED_USE validity checks."""

    feed_type = base.versioned_feed
    required_addons = (addons.UseAddon, addons.ProfileAddon)
    known_results = (MetadataError, RequiredUseDefaults) + addons.UseAddon.known_results

    def __init__(self, options, iuse_handler, profiles):
        super().__init__(options)
        self.iuse_filter = iuse_handler.get_filter('required_use')
        self.profiles = profiles

    def feed(self, pkg, reporter):
        # only run the check for EAPI 4 and above
        if not pkg.eapi.options.has_required_use:
            return

        # check REQUIRED_USE for invalid nodes
        for x in self.iuse_filter((str,), pkg, pkg.required_use, reporter):
            pass

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
                src = FakeConfigurable(pkg, profile)
                for node in pkg.required_use.evaluate_depset(src.use):
                    if not node.match(src.use):
                        failures[node].append((src.use, profile.key, profile.name))

        if self.options.verbosity > 0:
            # report all failures with profile info in verbose mode
            for node, profile_info in failures.items():
                for use, keyword, profile in profile_info:
                    reporter.add_report(RequiredUseDefaults(
                        pkg, node, use, keyword, profile))
        else:
            # only report one failure per REQUIRED_USE node in regular mode
            for node, profile_info in failures.items():
                num_profiles = len(profile_info)
                _use, _keyword, profile = profile_info[0]
                reporter.add_report(RequiredUseDefaults(
                    pkg, node, profile=profile, num_profiles=num_profiles))


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


class ProbableUSE_EXPAND(base.Warning):
    """Local USE flag that isn't overridden matches a USE_EXPAND group."""

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
    known_results = addons.UseAddon.known_results + (
        UnusedLocalUSE, MatchingGlobalUSE, ProbableGlobalUSE,
        ProbableUSE_EXPAND,
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

    def feed(self, pkgs, reporter):
        pkg = pkgs[0]
        local_use = pkg.local_use

        for flag, desc in local_use.items():
            if flag in self.global_use:
                ratio = SequenceMatcher(None, desc, self.global_use[flag]).ratio()
                if ratio == 1.0:
                    reporter.add_report(MatchingGlobalUSE(pkg, flag))
                elif ratio >= 0.75:
                    reporter.add_report(ProbableGlobalUSE(pkg, flag))
            else:
                for group in self.use_expand_groups:
                    if (flag.startswith(f'{group}_') and
                            flag not in self.use_expand_groups[group]):
                        reporter.add_report(ProbableUSE_EXPAND(pkg, flag, group.upper()))
                        break

        unused = set(local_use)
        for pkg in pkgs:
            unused.difference_update(pkg.iuse_stripped)
        if unused:
            reporter.add_report(UnusedLocalUSE(pkg, unused))


class MissingSlotDep(base.Warning):
    """Missing slot value in dependencies."""

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


class MissingSlotDepReport(base.Template):
    """Check for missing slot dependencies."""

    feed_type = base.versioned_feed
    required_addons = (addons.UseAddon,)
    known_results = (MissingSlotDep,) + addons.UseAddon.known_results

    def __init__(self, options, iuse_handler):
        super().__init__(options)
        self.iuse_filter = iuse_handler.get_filter()

    def feed(self, pkg, reporter):
        # only run the check for EAPI 5 and above
        if not pkg.eapi.options.sub_slotting:
            return

        rdepend = set(self.iuse_filter((atom_cls,), pkg, pkg.rdepend, reporter))
        depend = set(self.iuse_filter((atom_cls,), pkg, pkg.depend, reporter))
        # skip deps that are blockers or have explicit slots/slot operators
        for dep in (x for x in rdepend.intersection(depend) if not
                    (x.blocks or x.slot is not None or x.slot_operator is not None)):
            dep_slots = set(x.slot for x in pkg.repo.itermatch(dep))
            if len(dep_slots) > 1:
                reporter.add_report(MissingSlotDep(pkg, str(dep), dep_slots))


class MissingRevision(base.Warning):
    """Missing package revision in =cat/pkg dependencies.

    If any revision of the package is acceptable, the '~' operator should be
    used instead of '='. If only the initial revision of the dependency is
    allowed, '-r0' can be appended when using the '=' operator.
    """

    __slots__ = ('category', 'package', 'version', 'dep', 'atom')

    threshold = base.versioned_feed

    def __init__(self, pkg, dep, atom):
        super().__init__()
        self._store_cpv(pkg)
        self.dep = dep
        self.atom = str(atom)

    @property
    def short_desc(self):
        return f"{self.dep}: {self.atom}: '=' operator used without revision"


class MissingUseDepDefault(base.Warning):
    """Package dependencies with USE dependencies missing defaults."""

    __slots__ = ('category', 'package', 'version', 'attr', 'atom', 'flag', 'pkg_deps')

    threshold = base.versioned_feed

    def __init__(self, pkg, attr, atom, flag, pkg_deps):
        super().__init__()
        self._store_cpv(pkg)
        self.attr = attr
        self.atom = str(atom)
        self.pkg_deps = tuple(sorted(str(x.versioned_atom) for x in pkg_deps))
        self.flag = flag

    @property
    def short_desc(self):
        return (
            f"{self.attr}: {self.atom}: USE flag dep {self.flag!r} missing default "
            f"(matching package{_pl(self.pkg_deps)}: {', '.join(self.pkg_deps)})")


class OutdatedBlocker(base.Warning):
    """Blocker dependency removed more than two years ago from the tree.

    Note that this ignores slot/subslot deps and USE deps in blocker atoms.
    """

    __slots__ = ("category", "package", "version", "attr", "atom", "age")

    threshold = base.versioned_feed

    def __init__(self, pkg, attr, atom, age):
        super().__init__()
        self._store_cpv(pkg)
        self.attr = attr
        self.atom = atom
        self.age = age

    @property
    def short_desc(self):
        return (
            f"depset {self.attr}: outdated blocker '{self.atom}': "
            f'last matching version removed {self.age} years ago'
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
        self.attr = attr
        self.atom = atom

    @property
    def short_desc(self):
        return (
            f"depset {self.attr}: nonexistent blocker '{self.atom}': "
            'no matches in repo history'
        )


class GitRemovalRepo(object):
    """Parse repository git logs to determine ebuild removal dates."""

    def __init__(self, repo_path, commit):
        self.path = repo_path
        self.commit = commit
        self.pkg_map = self._process_git_repo()

    def update(self, commit):
        self._process_git_repo(self.pkg_map, self.commit)
        self.commit = commit

    def _process_git_repo(self, pkg_map=None, commit=None):
        if pkg_map is None:
            pkg_map = {}

        cmd = ['git', 'log', '--diff-filter=D', '--summary', '--date=short', '--reverse']
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
                if line.startswith(' delete mode '):
                    path = line.rsplit(' ', 1)[1]
                    match = ebuild_path_regex.match(path)
                    if match:
                        category = match.group(1)
                        pkgname = match.group(2)
                        pkg = match.group(3)
                        try:
                            a = atom_cls(f'={category}/{pkg}')
                            pkg_map.setdefault(
                                category, {}).setdefault(pkgname, []).append((a.fullver, date))
                        except MalformedAtom:
                            pass
        return pkg_map


class _RemovalRepo(object):
    """Repository supporting determining when a package version was removed."""

    def removal_date(self, pkg):
        for version, date in self.cpv_dict[pkg.category][pkg.package]:
            if version == pkg.fullver:
                return date


class HistoricalRepo(SimpleTree, _RemovalRepo):
    """Repository encapsulating historical data."""

    def _get_versions(self, cp_key):
        return tuple(version for version, date in self.cpv_dict[cp_key[0]][cp_key[1]])


class HistoricalMultiplexRepo(multiplex.tree, _RemovalRepo):
    """Multiplex-ed repo supporting historical queries across a repo and its masters."""


class DependencyReport(base.Template):
    """Check BDEPEND, DEPEND, RDEPEND, and PDEPEND."""

    required_addons = (addons.UseAddon, addons.GitAddon)
    known_results = (
        MetadataError, MissingRevision, MissingUseDepDefault,
        OutdatedBlocker, NonexistentBlocker,
        ) + addons.UseAddon.known_results

    feed_type = base.versioned_feed

    attrs = tuple((x, attrgetter(x)) for x in
                  ("bdepend", "depend", "rdepend", "pdepend"))

    def __init__(self, options, iuse_handler, _git_addon):
        super().__init__(options)
        self.iuse_filter = iuse_handler.get_filter()
        self.conditional_ops = {'?', '='}
        self.use_defaults = {'(+)', '(-)'}
        self.today = datetime.today()

        self.existence_repo = None
        if not options.git_disable:
            # initialize repos cache dir
            cache_dir = pjoin(base.CACHE_DIR, 'repos')
            try:
                os.makedirs(cache_dir, exist_ok=True)
            except IOError as e:
                raise UserException(
                    f'failed creating profiles cache: {cache_dir!r}: {e.strerror}')

            git_repos = []
            for repo in options.target_repo.trees:
                ret, out = spawn_get_output(
                    ['git', 'rev-parse', 'origin/HEAD'], cwd=repo.location)
                if ret != 0:
                    break
                else:
                    commit = out[0].strip()

                    # handle duplicate repo IDs that are repo paths
                    cache_file = repo.repo_id.lstrip(os.sep).replace(os.sep, '-')
                    cache_file = pjoin(cache_dir, f'{cache_file}.pickle')
                    git_repo = None
                    cache_repo = True
                    if not options.git_cache:
                        # try loading cached, historical repo data
                        try:
                            with open(cache_file, 'rb') as f:
                                git_repo = pickle.load(f)
                                if commit != git_repo.commit:
                                    git_repo.update(commit)
                                else:
                                    cache_repo = False
                        except (EOFError, FileNotFoundError, AttributeError):
                            pass

                    if git_repo is None:
                        git_repo = GitRemovalRepo(repo.location, commit)

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
                                if not options.forced_cache:
                                    logger.warn(msg)
                                else:
                                    raise UserException(msg)
            else:
                if len(git_repos) > 1:
                    self.existence_repo = HistoricalMultiplexRepo(*git_repos)
                elif len(git_repos) == 1:
                    self.existence_repo = git_repos[0]

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

    def feed(self, pkg, reporter):
        for attr_name, getter in self.attrs:
            slot_op_or_blocks = set()
            slot_op_blockers = set()
            outdated_blockers = set()
            nonexistent_blockers = set()

            i = self.iuse_filter(
                (atom_cls, OrRestriction), pkg, getter(pkg), reporter, attr=attr_name)
            for atom, in_or_restriction in self._flatten_or_restrictions(i):
                if pkg.eapi.options.has_use_dep_defaults and atom.use is not None:
                    missing_use_deps = self._check_use_deps(attr_name, pkg, atom)
                    for use, pkg_deps in missing_use_deps.items():
                        reporter.add_report(
                            MissingUseDepDefault(pkg, attr_name, atom, use, pkg_deps))
                if in_or_restriction and atom.slot_operator == '=':
                    slot_op_or_blocks.add(atom.key)
                if atom.blocks:
                    if atom.match(pkg):
                        reporter.add_report(MetadataError(pkg, attr_name, "blocks itself"))
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
                                removal = max(
                                    self.existence_repo.removal_date(x) for x in matches)
                                removal = datetime.strptime(removal, '%Y-%m-%d')
                                years = round((self.today - removal).days / 365, 2)
                                if years > 2:
                                    outdated_blockers.add((attr_name, atom, years))
                            else:
                                nonexistent_blockers.add((attr_name, atom))
                if atom.op == '=' and atom.revision is None:
                    reporter.add_report(MissingRevision(pkg, attr_name, atom))

            if slot_op_or_blocks:
                reporter.add_report(MetadataError(
                    pkg, attr_name,
                    "= slot operator used inside || block: [%s]" %
                    (', '.join(sorted(slot_op_or_blocks),))))
            if slot_op_blockers:
                reporter.add_report(MetadataError(
                    pkg, attr_name,
                    "= slot operator used in blocker: [%s]" %
                    (', '.join(sorted(slot_op_blockers),))))

            for attr, atom, years in sorted(outdated_blockers):
                reporter.add_report(OutdatedBlocker(pkg, attr, atom, years))
            for attr, atom in sorted(nonexistent_blockers):
                reporter.add_report(NonexistentBlocker(pkg, attr, atom))


class StupidKeywords(base.Warning):
    """Packages using ``-*``; use package.mask instead."""

    __slots__ = ('category', 'package', 'version')
    threshold = base.versioned_feed

    def __init__(self, pkg):
        super().__init__()
        self._store_cpv(pkg)

    short_desc = (
        "keywords contain -*; use package.mask or empty keywords instead")


class InvalidKeywords(base.Warning):
    """Packages using invalid KEYWORDS."""

    __slots__ = ('category', 'package', 'version', 'keywords')
    threshold = base.versioned_feed

    def __init__(self, pkg, keywords):
        super().__init__()
        self._store_cpv(pkg)
        self.keywords = tuple(keywords)

    @property
    def short_desc(self):
        return f"invalid KEYWORDS: {', '.join(self.keywords)}"


class OverlappingKeywords(base.Warning):
    """Packages having overlapping arch and ~arch KEYWORDS."""

    __slots__ = ('category', 'package', 'version', 'keywords')
    threshold = base.versioned_feed

    def __init__(self, pkg, keywords):
        super().__init__()
        self._store_cpv(pkg)
        self.keywords = []
        for x in sorted(keywords):
            self.keywords.extend([x, '~' + x])
        self.keywords = tuple(self.keywords)

    @property
    def short_desc(self):
        return f"overlapping KEYWORDS: {', '.join(self.keywords)}"


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
    with hyphens in them, e.g. amd64-fbsd) after regular arches and globs (e.g. -*)
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


class KeywordsReport(base.Template):
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
        # Note: '*' and '~*' are portage-only special KEYWORDS atm, i.e. not
        # in PMS or implemented in pkgcore.
        special_keywords = set(('-*', '*', '~*'))
        stable_keywords = self.valid_arches
        unstable_keywords = set('~' + x for x in self.valid_arches)
        disabled_keywords = set('-' + x for x in self.valid_arches)
        self.valid_keywords = (
            special_keywords | stable_keywords | unstable_keywords | disabled_keywords)

    def feed(self, pkg, reporter):
        if len(pkg.keywords) == 1 and pkg.keywords[0] == "-*":
            reporter.add_report(StupidKeywords(pkg))
        else:
            # check for invalid keywords
            invalid = set(pkg.keywords) - self.valid_keywords
            if invalid:
                reporter.add_report(InvalidKeywords(pkg, invalid))

            # check for overlapping keywords
            unstable = {x[1:] for x in pkg.keywords if x[0] == '~'}
            stable = {x for x in pkg.keywords if x[0] != '~'}
            overlapping = unstable & stable
            if overlapping:
                reporter.add_report(OverlappingKeywords(pkg, overlapping))

            # check for duplicate keywords
            duplicates = set()
            seen = set()
            for x in pkg.keywords:
                if x not in seen:
                    seen.add(x)
                else:
                    duplicates.add(x)
            if duplicates:
                reporter.add_report(DuplicateKeywords(pkg, duplicates))

            # check for unsorted keywords
            if pkg.sorted_keywords != pkg.keywords:
                reporter.add_report(UnsortedKeywords(pkg))

            if pkg.category == 'virtual':
                keywords = set()
                rdepend = set(self.iuse_filter((atom_cls,), pkg, pkg.rdepend, reporter))
                for x in rdepend:
                    for p in self.options.search_repo.match(strip_atom_use(x)):
                        keywords.update(p.keywords)
                keywords = keywords | {f'~{x}' for x in keywords if x in self.valid_arches}
                missing_keywords = set(pkg.keywords) - keywords
                if missing_keywords:
                    reporter.add_report(MissingVirtualKeywords(pkg, missing_keywords))


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

    Archive filenames should be disambiguated using '->' to rename them.
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


class SrcUriReport(base.Template):
    """SRC_URI related checks.

    Verify that URIs are valid, fetchable, using a supported protocol, and
    don't use unspecific filenames.
    """

    required_addons = (addons.UseAddon,)
    feed_type = base.versioned_feed
    known_results = (BadFilename, BadProto, MissingUri, MetadataError, UnknownMirror) + \
        addons.UseAddon.known_results

    valid_protos = frozenset(["http", "https", "ftp"])

    def __init__(self, options, iuse_handler):
        super().__init__(options)
        self.iuse_filter = iuse_handler.get_filter('fetchables')

    def feed(self, pkg, reporter):
        lacks_uri = set()
        # duplicate entries are possible.
        seen = set()
        bad_filenames = set()
        fetchables = set(self.iuse_filter(
            (fetchable,), pkg,
            pkg._get_attr['fetchables'](
                pkg, allow_missing_checksums=True,
                ignore_unknown_mirrors=True, skip_default_mirrors=True),
            reporter))
        for f_inst in fetchables:
            if f_inst.filename in seen:
                continue
            seen.add(f_inst.filename)

            mirrors = f_inst.uri.visit_mirrors(treat_default_as_mirror=False)
            unknown_mirrors = [
                (m, sub_uri) for m, sub_uri in mirrors if isinstance(m, unknown_mirror)]
            for mirror, sub_uri in unknown_mirrors:
                uri = f"{mirror}/{sub_uri}"
                reporter.add_report(
                    UnknownMirror(pkg, f_inst.filename, uri, mirror.mirror_name))

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
                if bad:
                    reporter.add_report(
                        BadProto(pkg, f_inst.filename, bad))
        if "fetch" not in pkg.restrict:
            for x in sorted(lacks_uri):
                reporter.add_report(MissingUri(pkg, x))

        if bad_filenames:
            reporter.add_report(BadFilename(pkg, bad_filenames))


class BadDescription(base.Warning):
    """Package's description sucks in some fashion."""

    __slots__ = ("category", "package", "version", "msg")
    threshold = base.versioned_feed

    def __init__(self, pkg, msg):
        super().__init__()
        self._store_cpv(pkg)
        self.msg = msg

    @property
    def short_desc(self):
        return f"description needs improvement: {self.msg}"


class DescriptionReport(base.Template):
    """DESCRIPTION checks.

    Check on length (<=150), too short (<10), or generic (lifted from eclass or
    just using the package's name.
    """

    feed_type = base.versioned_feed
    known_results = (BadDescription,)

    def feed(self, pkg, reporter):
        s = pkg.description.lower()

        if s.startswith("based on") and "eclass" in s:
            reporter.add_report(BadDescription(
                pkg, "generic eclass defined description"))

        elif pkg.package == s or pkg.key == s:
            reporter.add_report(BadDescription(
                pkg, "using the pkg name as the description isn't very helpful"))

        else:
            l = len(pkg.description)
            if not l:
                reporter.add_report(BadDescription(
                    pkg, "empty/unset"))
            elif l > 150:
                reporter.add_report(BadDescription(
                    pkg, "over 150 chars in length, bit long"))
            elif l < 10:
                reporter.add_report(BadDescription(
                    pkg, f"{pkg.description!r} under 10 chars in length- too short"))


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


class RestrictsReport(base.Template):
    feed_type = base.versioned_feed
    known_restricts = frozenset((
        "binchecks", "bindist", "fetch", "installsources", "mirror",
        "primaryuri", "splitdebug", "strip", "test", "userpriv",
    ))

    known_results = (BadRestricts,) + addons.UseAddon.known_results
    required_addons = (addons.UseAddon,)

    __doc__ = "check over RESTRICT, looking for unknown restricts\nvalid " \
        "restricts: %s" % ", ".join(sorted(known_restricts))

    def __init__(self, options, iuse_handler):
        super().__init__(options)
        self.iuse_filter = iuse_handler.get_filter('restrict')

    def feed(self, pkg, reporter):
        # ignore conditionals
        i = self.iuse_filter((str,), pkg, pkg.restrict, reporter)
        bad = set(i).difference(self.known_restricts)
        if bad:
            deprecated = set(
                x for x in bad if x.startswith("no") and x[2:] in self.known_restricts)
            reporter.add_report(BadRestricts(
                pkg, bad.difference(deprecated), deprecated))
