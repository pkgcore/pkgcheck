from collections import defaultdict
from difflib import SequenceMatcher
from itertools import chain, groupby
from operator import attrgetter, itemgetter

from pkgcore import fetch
from snakeoil.contexts import patch
from snakeoil.klass import jit_attr
from snakeoil.log import suppress_logging
from snakeoil.sequences import iflatten_instance
from snakeoil.strings import pluralism as _pl

from .. import addons, base


class MultiMovePackageUpdate(base.Warning):
    """Entry for package moved multiple times in profiles/updates files."""

    threshold = base.repository_feed

    def __init__(self, pkg, moves):
        super().__init__()
        self.pkg = pkg
        self.moves = tuple(moves)

    @property
    def desc(self):
        return f"{self.pkg!r}: multi-move update: {' -> '.join(self.moves)}"


class OldMultiMovePackageUpdate(base.Warning):
    """Old entry for removed package moved multiple times in profiles/updates files.

    This means that the reported pkg has been moved at least three times and
    finally removed from the tree. All the related lines should be removed from
    the update files.
    """

    threshold = base.repository_feed

    def __init__(self, pkg, moves):
        super().__init__()
        self.pkg = pkg
        self.moves = tuple(moves)

    @property
    def desc(self):
        return f"{self.pkg!r} unavailable: old multi-move update: {' -> '.join(self.moves)}"


class OldPackageUpdate(base.Warning):
    """Old entry for removed package in profiles/updates files."""

    threshold = base.repository_feed

    def __init__(self, pkg, updates):
        super().__init__()
        self.pkg = pkg
        self.updates = tuple(updates)

    @property
    def desc(self):
        return f"{self.pkg!r} unavailable: old update line: {' '.join(self.updates)!r}"


class MovedPackageUpdate(base.LogWarning):
    """Entry for package already moved in profiles/updates files."""

    threshold = base.repository_feed


class BadPackageUpdate(base.LogError):
    """Badly formatted package update in profiles/updates files."""

    threshold = base.repository_feed


class PackageUpdatesCheck(base.Check, base.EmptyFeed):
    """Scan profiles/updates/* for outdated entries and other issues."""

    feed_type = base.repository_feed
    scope = base.repository_scope
    known_results = (
        MultiMovePackageUpdate, OldMultiMovePackageUpdate,
        OldPackageUpdate, MovedPackageUpdate, BadPackageUpdate,
    )

    def __init__(self, options):
        super().__init__(options)
        self.repo = options.target_repo

    def finish(self):
        update_reports = []
        report_bad_updates = lambda x: update_reports.append(BadPackageUpdate(x))
        report_old_updates = lambda x: update_reports.append(MovedPackageUpdate(x))

        # convert log warnings/errors into reports
        with patch('pkgcore.log.logger.error', report_bad_updates), \
                patch('pkgcore.log.logger.warning', report_old_updates):
            repo_updates = self.repo.config.updates

        yield from update_reports

        multi_move_updates = {}
        old_move_updates = {}
        old_slotmove_updates = {}

        for pkg, updates in repo_updates.items():
            move_updates = [x for x in updates if x[0] == 'move']
            slotmove_updates = [x for x in updates if x[0] == 'slotmove']

            # check for multi-updates, a -> b, b -> c, ...
            if len(move_updates) > 1:
                # the most recent move should override all the older entries,
                # meaning only a single report for the entire chain should created
                multi_move_updates[move_updates[-1][2]] = (pkg, [x[2] for x in move_updates])
            else:
                # scan updates for old entries with removed packages
                for x in move_updates:
                    _, _old, new = x
                    if not self.repo.match(new):
                        old_move_updates[new] = x

            # scan updates for old entries with removed packages
            for x in slotmove_updates:
                _, pkg, newslot = x
                if not self.repo.match(pkg.unversioned_atom):
                    # reproduce updates file line data for result output
                    x = ('slotmove', str(pkg)[:-(len(pkg.slot) + 1)], pkg.slot, newslot)
                    old_slotmove_updates[pkg.key] = x

        for pkg, v in multi_move_updates.items():
            orig_pkg, moves = v
            # check for multi-move chains ending in removed packages
            moves = [str(orig_pkg)] + list(map(str, moves))
            if not self.repo.match(pkg):
                yield OldMultiMovePackageUpdate(str(moves[-1]), moves)
                # don't generate duplicate old report
                old_move_updates.pop(pkg, None)
            else:
                yield MultiMovePackageUpdate(str(orig_pkg), moves)

        # report remaining old updates
        for pkg, move in chain(old_move_updates.items(), old_slotmove_updates.items()):
            updates = map(str, move)
            yield OldPackageUpdate(str(pkg), updates)


class UnusedLicenses(base.Warning):
    """Unused license(s) detected."""

    threshold = base.repository_feed

    def __init__(self, licenses):
        super().__init__()
        self.licenses = tuple(licenses)

    @property
    def desc(self):
        licenses = ', '.join(self.licenses)
        return f'unused license{_pl(self.licenses)}: {licenses}'


class UnusedLicensesCheck(base.Check):
    """Check for unused license files."""

    feed_type = base.versioned_feed
    scope = base.repository_scope
    known_results = (UnusedLicenses,)

    def __init__(self, options):
        super().__init__(options)
        self.unused_licenses = None

    def start(self):
        master_licenses = set()
        for repo in self.options.target_repo.masters:
            master_licenses.update(repo.licenses)
        self.unused_licenses = set(self.options.target_repo.licenses) - master_licenses

    def feed(self, pkg):
        self.unused_licenses.difference_update(iflatten_instance(pkg.license))

    def finish(self):
        if self.unused_licenses:
            yield UnusedLicenses(sorted(self.unused_licenses))


class UnusedMirrors(base.Warning):
    """Unused mirrors detected."""

    threshold = base.repository_feed

    def __init__(self, mirrors):
        super().__init__()
        self.mirrors = tuple(mirrors)

    @property
    def desc(self):
        mirrors = ', '.join(self.mirrors)
        return f'unused mirror{_pl(self.mirrors)}: {mirrors}'


class _MirrorsCheck(base.Check):
    """Check for unused mirrors."""

    required_addons = (addons.UseAddon,)

    def __init__(self, options, iuse_handler):
        super().__init__(options)
        self.iuse_filter = iuse_handler.get_filter('fetchables')

    def _get_mirrors(self, pkg):
        mirrors = []
        fetchables, _ = self.iuse_filter(
            (fetch.fetchable,), pkg,
            pkg._get_attr['fetchables'](
                pkg, allow_missing_checksums=True, ignore_unknown_mirrors=True))
        for f in fetchables:
            for m in f.uri.visit_mirrors(treat_default_as_mirror=False):
                mirrors.append(m[0].mirror_name)
        return set(mirrors)


class UnusedMirrorsCheck(_MirrorsCheck):
    """Check for unused mirrors."""

    feed_type = base.versioned_feed
    scope = base.repository_scope
    known_results = (UnusedMirrors,)

    def start(self):
        master_mirrors = set()
        for repo in self.options.target_repo.masters:
            master_mirrors.update(repo.mirrors.keys())
        self.unused_mirrors = set(self.options.target_repo.mirrors.keys()) - master_mirrors

    def feed(self, pkg):
        if self.unused_mirrors:
            self.unused_mirrors.difference_update(self._get_mirrors(pkg))

    def finish(self):
        if self.unused_mirrors:
            yield UnusedMirrors(sorted(self.unused_mirrors))


class UnusedEclasses(base.Warning):
    """Unused eclasses detected."""

    threshold = base.repository_feed

    def __init__(self, eclasses):
        super().__init__()
        self.eclasses = tuple(eclasses)

    @property
    def desc(self):
        eclasses = ', '.join(self.eclasses)
        return f"unused eclass{_pl(self.eclasses, plural='es')}: {eclasses}"


class UnusedEclassesCheck(base.Check):
    """Check for unused eclasses."""

    feed_type = base.versioned_feed
    scope = base.repository_scope
    known_results = (UnusedEclasses,)

    def __init__(self, options):
        super().__init__(options)
        self.unused_eclasses = None

    def start(self):
        master_eclasses = set()
        for repo in self.options.target_repo.masters:
            master_eclasses.update(repo.eclass_cache.eclasses.keys())
        self.unused_eclasses = set(
            self.options.target_repo.eclass_cache.eclasses.keys()) - master_eclasses

    def feed(self, pkg):
        self.unused_eclasses.difference_update(pkg.inherited)

    def finish(self):
        if self.unused_eclasses:
            yield UnusedEclasses(sorted(self.unused_eclasses))


class UnknownLicenses(base.Warning):
    """License(s) listed in license group(s) that don't exist."""

    threshold = base.repository_feed

    def __init__(self, group, licenses):
        super().__init__()
        self.group = group
        self.licenses = tuple(licenses)

    @property
    def desc(self):
        return "license group %r has unknown license%s: [ %s ]" % (
            self.group, _pl(self.licenses), ', '.join(self.licenses))


class LicenseGroupsCheck(base.Check, base.EmptyFeed):
    """Scan license groups for unknown licenses."""

    feed_type = base.repository_feed
    scope = base.repository_scope
    known_results = (UnknownLicenses,)

    def __init__(self, options):
        super().__init__(options)
        self.repo = options.target_repo

    def finish(self):
        for group, licenses in self.repo.licenses.groups.items():
            unknown_licenses = set(licenses).difference(self.repo.licenses)
            if unknown_licenses:
                yield UnknownLicenses(group, sorted(unknown_licenses))


class PotentialLocalUSE(base.Info):
    """Global USE flag is a potential local USE flag."""

    threshold = base.repository_feed

    def __init__(self, flag, pkgs):
        super().__init__()
        self.flag = flag
        self.pkgs = tuple(pkgs)

    @property
    def desc(self):
        return (
            f"global USE flag {self.flag!r} is a potential local, "
            f"used by {len(self.pkgs)} package{_pl(len(self.pkgs))}: {', '.join(self.pkgs)}")


class UnusedGlobalUSE(base.Warning):
    """Unused use.desc flag(s)."""

    threshold = base.repository_feed

    def __init__(self, flags):
        super().__init__()
        self.flags = tuple(flags)

    @property
    def desc(self):
        return "use.desc unused flag%s: %s" % (
            _pl(self.flags), ', '.join(self.flags))


class PotentialGlobalUSE(base.Info):
    """Local USE flag is a potential global USE flag."""

    threshold = base.repository_feed

    def __init__(self, flag, pkgs):
        super().__init__()
        self.flag = flag
        self.pkgs = tuple(pkgs)

    @property
    def desc(self):
        return (
            f"local USE flag {self.flag!r} is a potential global "
            f"used by {len(self.pkgs)} packages: {', '.join(self.pkgs)}")


def _dfs(graph, start, visited=None):
    if visited is None:
        visited = set()
    visited.add(start)
    for node in graph[start] - visited:
        _dfs(graph, node, visited)
    return visited


class GlobalUSECheck(base.Check):
    """Check global USE and USE_EXPAND flags for various issues."""

    feed_type = base.package_feed
    scope = base.repository_scope
    required_addons = (addons.UseAddon,)
    known_results = (PotentialLocalUSE, PotentialGlobalUSE, UnusedGlobalUSE)

    def __init__(self, options, iuse_handler):
        super().__init__(options)
        self.global_flag_usage = defaultdict(set)
        self.repo = options.target_repo

    @jit_attr
    def local_use(self):
        return self.repo.config.use_local_desc

    @jit_attr
    def global_use(self):
        return {flag: desc for matcher, (flag, desc) in self.repo.config.use_desc}

    @jit_attr
    def use_expand(self):
        return {
            flag: desc for flags in self.repo.config.use_expand_desc.values()
            for flag, desc in flags}

    def start(self):
        master_flags = set()
        for repo in self.options.target_repo.masters:
            master_flags.update(flag for matcher, (flag, desc) in repo.config.use_desc)

    def feed(self, pkgs):
        # ignore bad XML, it will be caught by metadata.xml checks
        with suppress_logging():
            local_use = set(pkgs[0].local_use.keys())
        for pkg in pkgs:
            pkg_global_use = pkg.iuse_stripped.difference(local_use)
            for flag in pkg_global_use:
                self.global_flag_usage[flag].add(pkg.unversioned_atom)

    @staticmethod
    def _similar_flags(pkgs):
        """Yield groups of packages with similar local USE flag descriptions."""
        # calculate USE flag description difference ratios
        diffs = {}
        for i, (i_pkg, i_desc) in enumerate(pkgs):
            for j, (j_pkg, j_desc) in enumerate(pkgs[i + 1:]):
                diffs[(i, i + j + 1)] = SequenceMatcher(None, i_desc, j_desc).ratio()

        # create an adjacency list using all closely matching flags pairs
        similar = defaultdict(set)
        for (i, j), r in diffs.items():
            if r >= 0.75:
                similar[i].add(j)
                similar[j].add(i)

        # not enough close matches found
        if len(similar.keys()) < 5:
            return

        # determine groups of connected components
        nodes = set(similar.keys())
        components = []
        while nodes:
            visited = _dfs(similar, nodes.pop())
            components.append(visited)
            nodes -= visited

        # Flag groups of five or more pkgs with similar local USE flags as a
        # potential globals -- note that this can yield the same flag for
        # multiple, distinct descriptions.
        for component in components:
            if len(component) >= 5:
                yield [pkgs[i][0] for i in component]

    def finish(self):
        unused_global_flags = []
        potential_locals = []
        for flag in self.global_use.keys():
            pkgs = self.global_flag_usage[flag]
            if not pkgs:
                unused_global_flags.append(flag)
            elif len(pkgs) < 5:
                potential_locals.append((flag, pkgs))

        if unused_global_flags:
            yield UnusedGlobalUSE(sorted(unused_global_flags))
        for flag, pkgs in sorted(potential_locals, key=lambda x: len(x[1])):
            pkgs = sorted(map(str, pkgs))
            yield PotentialLocalUSE(flag, pkgs)

        local_use = defaultdict(list)
        for pkg, (flag, desc) in self.local_use:
            if flag not in self.global_use:
                local_use[flag].append((pkg, desc))

        potential_globals = []
        for flag, pkgs in sorted((k, v) for k, v in local_use.items() if len(v) >= 5):
            for matching_pkgs in self._similar_flags(pkgs):
                potential_globals.append((flag, matching_pkgs))

        for flag, pkgs in sorted(potential_globals, key=lambda x: len(x[1]), reverse=True):
            pkgs = sorted(map(str, pkgs))
            yield PotentialGlobalUSE(flag, pkgs)


def reformat_chksums(iterable):
    for chf, val1, val2 in iterable:
        if chf == "size":
            yield chf, val1, val2
        else:
            yield chf, "%x" % val1, "%x" % val2


class ConflictingChksums(base.VersionedResult, base.Error):
    """Checksum conflict detected between two files."""

    def __init__(self, filename, chksums, pkgs, **kwargs):
        super().__init__(**kwargs)
        self.filename = filename
        self.chksums = tuple(chksums)
        self.pkgs = tuple(pkgs)

    @property
    def desc(self):
        return (
            f"conflicts with ({', '.join(self.pkgs)}) "
            f"for file {self.filename!r} chksum {self.chksums}")


class MissingChksum(base.VersionedResult, base.Warning):
    """A file in the chksum data lacks required checksums."""

    def __init__(self, filename, missing, existing, **kwargs):
        super().__init__(**kwargs)
        self.filename = filename
        self.missing = tuple(missing)
        self.existing = tuple(existing)

    @property
    def desc(self):
        return (
            f"{self.filename!r} missing required chksums: "
            f"{', '.join(self.missing)}; has chksums: {', '.join(self.existing)}")


class DeprecatedChksum(base.VersionedResult, base.Warning):
    """A file in the chksum data does not use modern checksum set."""

    def __init__(self, filename, expected, existing, **kwargs):
        super().__init__(**kwargs)
        self.filename = filename
        self.expected = tuple(expected)
        self.existing = tuple(existing)

    @property
    def desc(self):
        return (
            f"{self.filename!r} uses deprecated checksum set: "
            f"{', '.join(self.existing)}; expected {', '.join(self.expected)}")


class MissingManifest(base.VersionedResult, base.Error):
    """SRC_URI targets missing from Manifest file."""

    def __init__(self, files, **kwargs):
        super().__init__(**kwargs)
        self.files = tuple(files)

    @property
    def desc(self):
        return "distfile%s missing from Manifest: [ %s ]" % (
            _pl(self.files), ', '.join(self.files),)


class UnknownManifest(base.PackageResult, base.Warning):
    """Manifest entries not matching any SRC_URI targets."""

    def __init__(self, files, **kwargs):
        super().__init__(**kwargs)
        self.files = tuple(files)

    @property
    def desc(self):
        return "unknown distfile%s in Manifest: [ %s ]" % (
            _pl(self.files), ', '.join(self.files),)


class UnnecessaryManifest(base.PackageResult, base.Warning):
    """Manifest entries for non-DIST targets on a repo with thin manifests enabled."""

    def __init__(self, files, **kwargs):
        super().__init__(**kwargs)
        self.files = tuple(files)

    @property
    def desc(self):
        return "unnecessary file%s in Manifest: [ %s ]" % (
            _pl(self.files), ', '.join(self.files),)


class ManifestCheck(base.Check):
    """Manifest related checks.

    Verify that the Manifest file exists, doesn't have missing or
    extraneous entries, and that the required hashes are in use.
    """

    required_addons = (addons.UseAddon,)
    scope = base.package_scope
    feed_type = base.package_feed
    known_results = (
        MissingChksum, MissingManifest, UnknownManifest, UnnecessaryManifest,
        DeprecatedChksum,
    )

    def __init__(self, options, iuse_handler):
        super().__init__(options)
        repo = options.target_repo
        self.preferred_checksums = frozenset(
            repo.config.manifests.hashes if hasattr(repo, 'config') else ())
        self.required_checksums = frozenset(
            repo.config.manifests.required_hashes if hasattr(repo, 'config') else ())
        self.iuse_filter = iuse_handler.get_filter('fetchables')

    def feed(self, pkgset):
        pkg_manifest = pkgset[0].manifest
        manifest_distfiles = set(pkg_manifest.distfiles.keys())
        seen = set()
        for pkg in pkgset:
            pkg.release_cached_data()
            fetchables, _ = self.iuse_filter(
                (fetch.fetchable,), pkg,
                pkg._get_attr['fetchables'](
                    pkg, allow_missing_checksums=True, ignore_unknown_mirrors=True))
            fetchables = set(fetchables)
            pkg.release_cached_data()

            fetchable_files = set(f.filename for f in fetchables)
            missing_manifests = fetchable_files.difference(manifest_distfiles)
            if missing_manifests:
                yield MissingManifest(sorted(missing_manifests), pkg=pkg)

            for f_inst in fetchables:
                if f_inst.filename in seen:
                    continue
                missing = self.required_checksums.difference(f_inst.chksums)
                if f_inst.filename not in missing_manifests and missing:
                    yield MissingChksum(
                        f_inst.filename, sorted(missing),
                        sorted(f_inst.chksums), pkg=pkg)
                elif f_inst.chksums and self.preferred_checksums != frozenset(f_inst.chksums):
                    yield DeprecatedChksum(
                        f_inst.filename, sorted(self.preferred_checksums),
                        sorted(f_inst.chksums), pkg=pkg)
                seen.add(f_inst.filename)

        if pkg_manifest.thin:
            unnecessary_manifests = []
            for attr in ('aux_files', 'ebuilds', 'misc'):
                unnecessary_manifests.extend(getattr(pkg_manifest, attr, []))
            if unnecessary_manifests:
                yield UnnecessaryManifest(sorted(unnecessary_manifests), pkg=pkgset[0])

        unknown_manifests = manifest_distfiles.difference(seen)
        if unknown_manifests:
            yield UnknownManifest(sorted(unknown_manifests), pkg=pkgset[0])


class ManifestConflictCheck(base.Check):
    """Conflicting checksum check.

    Verify that two Manifest files do not contain conflicting checksums
    for the same filename.
    """

    scope = base.repository_scope
    feed_type = base.package_feed
    known_results = (ConflictingChksums,)

    repo_grabber = attrgetter("repo")

    def __init__(self, options):
        super().__init__(options)
        self.seen_checksums = {}

    def feed(self, full_pkgset):
        # sort it by repo.
        for repo, pkgset in groupby(full_pkgset, self.repo_grabber):
            pkg = next(iter(pkgset))
            for filename, chksums in pkg.manifest.distfiles.items():
                existing = self.seen_checksums.get(filename)
                if existing is None:
                    self.seen_checksums[filename] = (
                        [pkg.key], dict(chksums.items()))
                    continue
                seen_pkgs, seen_chksums = existing
                confl_checksums = []
                for chf_type, value in seen_chksums.items():
                    our_value = chksums.get(chf_type)
                    if our_value is not None and our_value != value:
                        confl_checksums.append((chf_type, value, our_value))
                if confl_checksums:
                    chksums = sorted(reformat_chksums(confl_checksums), key=itemgetter(0))
                    pkgs = map(str, sorted(seen_pkgs))
                    yield ConflictingChksums(filename, chksums, pkgs, pkg=pkg)
                else:
                    seen_chksums.update(chksums)
                    seen_pkgs.append(pkg)
