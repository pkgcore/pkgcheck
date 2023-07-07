import re
from collections import defaultdict
from difflib import SequenceMatcher
from itertools import chain

from pkgcore import fetch
from pkgcore.ebuild.digest import Manifest
from snakeoil.sequences import iflatten_instance
from snakeoil.strings import pluralism

from .. import addons, base, results, sources
from . import Check, MirrorsCheck, RepoCheck


DEPRECATED_HASHES = frozenset({"md5", "rmd160", "sha1", "whirlpool"})


class MultiMovePackageUpdate(results.ProfilesResult, results.Warning):
    """Entry for package moved multiple times in profiles/updates files."""

    def __init__(self, pkg, moves):
        super().__init__()
        self.pkg = pkg
        self.moves = tuple(moves)

    @property
    def desc(self):
        return f"{self.pkg!r}: multi-move update: {' -> '.join(self.moves)}"


class OldMultiMovePackageUpdate(results.ProfilesResult, results.Warning):
    """Old entry for removed package moved multiple times in profiles/updates files.

    This means that the reported pkg has been moved at least three times and
    finally removed from the tree. All the related lines should be removed from
    the update files.
    """

    def __init__(self, pkg, moves):
        super().__init__()
        self.pkg = pkg
        self.moves = tuple(moves)

    @property
    def desc(self):
        return f"{self.pkg!r} unavailable: old multi-move update: {' -> '.join(self.moves)}"


class OldPackageUpdate(results.ProfilesResult, results.Warning):
    """Old entry for removed package in profiles/updates files."""

    def __init__(self, pkg, updates):
        super().__init__()
        self.pkg = pkg
        self.updates = tuple(updates)

    @property
    def desc(self):
        return f"{self.pkg!r} unavailable: old update line: {' '.join(self.updates)!r}"


class RedundantPackageUpdate(results.ProfilesResult, results.Warning):
    """Move entry to the same package/slot (source == target)."""

    def __init__(self, updates):
        super().__init__()
        self.updates = tuple(updates)

    @property
    def desc(self):
        return f"update line moves to the same package/slot: {' '.join(self.updates)!r}"


class MovedPackageUpdate(results.ProfilesResult, results.LogWarning):
    """Entry for package already moved in profiles/updates files."""


class BadPackageUpdate(results.ProfilesResult, results.LogError):
    """Badly formatted package update in profiles/updates files."""


class PackageUpdatesCheck(RepoCheck):
    """Scan profiles/updates/* for outdated entries and other issues."""

    _source = (sources.EmptySource, (base.profiles_scope,))
    known_results = frozenset(
        {
            MultiMovePackageUpdate,
            OldMultiMovePackageUpdate,
            OldPackageUpdate,
            MovedPackageUpdate,
            BadPackageUpdate,
            RedundantPackageUpdate,
        }
    )

    def __init__(self, *args):
        super().__init__(*args)
        self.repo = self.options.target_repo
        self.search_repo = self.options.search_repo

    def finish(self):
        logmap = (
            base.LogMap("pkgcore.log.logger.warning", MovedPackageUpdate),
            base.LogMap("pkgcore.log.logger.error", BadPackageUpdate),
        )

        # convert log warnings/errors into reports
        with base.LogReports(*logmap) as log_reports:
            repo_updates = self.repo.config.updates
        yield from log_reports

        multi_move_updates = {}
        old_move_updates = {}
        old_slotmove_updates = {}

        for pkg, updates in repo_updates.items():
            move_updates = [x for x in updates if x[0] == "move"]
            slotmove_updates = [x for x in updates if x[0] == "slotmove"]

            # check for multi-updates, a -> b, b -> c, ...
            if len(move_updates) > 1:
                # the most recent move should override all the older entries,
                # meaning only a single report for the entire chain should created
                multi_move_updates[move_updates[-1][2]] = (pkg, [x[2] for x in move_updates])
            else:
                # scan updates for old entries with removed packages
                for x in move_updates:
                    _, old, new = x
                    if not self.search_repo.match(new):
                        old_move_updates[new] = x
                    if old == new:
                        yield RedundantPackageUpdate(map(str, x))

            # scan updates for old entries with removed packages
            for x in slotmove_updates:
                _, pkg, newslot = x
                orig_line = ("slotmove", str(pkg)[: -(len(pkg.slot) + 1)], pkg.slot, newslot)
                if not self.search_repo.match(pkg.unversioned_atom):
                    # reproduce updates file line data for result output
                    old_slotmove_updates[pkg.key] = orig_line
                if pkg.slot == newslot:
                    yield RedundantPackageUpdate(map(str, orig_line))

        for pkg, v in multi_move_updates.items():
            orig_pkg, moves = v
            # check for multi-move chains ending in removed packages
            moves = [str(orig_pkg)] + list(map(str, moves))
            if not self.search_repo.match(pkg):
                yield OldMultiMovePackageUpdate(str(moves[-1]), moves)
                # don't generate duplicate old report
                old_move_updates.pop(pkg, None)
            else:
                yield MultiMovePackageUpdate(str(orig_pkg), moves)

        # report remaining old updates
        for pkg, move in chain(old_move_updates.items(), old_slotmove_updates.items()):
            updates = map(str, move)
            yield OldPackageUpdate(str(pkg), updates)


class UnusedLicenses(results.Warning):
    """Unused license(s) detected."""

    def __init__(self, licenses):
        super().__init__()
        self.licenses = tuple(licenses)

    @property
    def desc(self):
        s = pluralism(self.licenses)
        licenses = ", ".join(self.licenses)
        return f"unused license{s}: {licenses}"


class UnusedLicensesCheck(RepoCheck):
    """Check for unused license files."""

    _source = sources.RepositoryRepoSource
    known_results = frozenset({UnusedLicenses})

    def __init__(self, *args):
        super().__init__(*args)
        self.unused_licenses = None

    def start(self):
        master_licenses = set()
        for repo in self.options.target_repo.masters:
            master_licenses.update(repo.licenses)
        self.unused_licenses = set(self.options.target_repo.licenses) - master_licenses

    def feed(self, pkg):
        self.unused_licenses.difference_update(iflatten_instance(pkg.license))
        yield from ()

    def finish(self):
        if self.unused_licenses:
            yield UnusedLicenses(sorted(self.unused_licenses))


class UnusedMirrors(results.Warning):
    """Unused mirrors detected."""

    def __init__(self, mirrors):
        super().__init__()
        self.mirrors = tuple(mirrors)

    @property
    def desc(self):
        s = pluralism(self.mirrors)
        mirrors = ", ".join(self.mirrors)
        return f"unused mirror{s}: {mirrors}"


class UnusedMirrorsCheck(MirrorsCheck, RepoCheck):
    """Check for unused mirrors."""

    _source = sources.RepositoryRepoSource
    known_results = frozenset({UnusedMirrors})

    def start(self):
        master_mirrors = set()
        for repo in self.options.target_repo.masters:
            master_mirrors.update(repo.mirrors.keys())
        self.unused_mirrors = set(self.options.target_repo.mirrors.keys()) - master_mirrors

    def feed(self, pkg):
        if self.unused_mirrors:
            self.unused_mirrors.difference_update(self.get_mirrors(pkg))
        yield from ()

    def finish(self):
        if self.unused_mirrors:
            yield UnusedMirrors(sorted(self.unused_mirrors))


class UnusedEclasses(results.Warning):
    """Unused eclasses detected."""

    def __init__(self, eclasses):
        super().__init__()
        self.eclasses = tuple(eclasses)

    @property
    def desc(self):
        es = pluralism(self.eclasses, plural="es")
        eclasses = ", ".join(self.eclasses)
        return f"unused eclass{es}: {eclasses}"


class UnusedEclassesCheck(RepoCheck):
    """Check for unused eclasses."""

    _source = sources.RepositoryRepoSource
    known_results = frozenset({UnusedEclasses})

    def __init__(self, *args):
        super().__init__(*args)
        self.unused_eclasses = None

    def start(self):
        master_eclasses = set()
        for repo in self.options.target_repo.masters:
            master_eclasses.update(repo.eclass_cache.eclasses.keys())
        self.unused_eclasses = (
            set(self.options.target_repo.eclass_cache.eclasses.keys()) - master_eclasses
        )

    def feed(self, pkg):
        self.unused_eclasses.difference_update(pkg.inherited)
        yield from ()

    def finish(self):
        if self.unused_eclasses:
            yield UnusedEclasses(sorted(self.unused_eclasses))


class UnknownLicenses(results.Warning):
    """License(s) listed in license group(s) that don't exist."""

    def __init__(self, group, licenses):
        super().__init__()
        self.group = group
        self.licenses = tuple(licenses)

    @property
    def desc(self):
        s = pluralism(self.licenses)
        licenses = ", ".join(self.licenses)
        return f"license group {self.group!r} has unknown license{s}: [ {licenses} ]"


class LicenseGroupsCheck(RepoCheck):
    """Scan license groups for unknown licenses."""

    _source = (sources.EmptySource, (base.repo_scope,))
    known_results = frozenset({UnknownLicenses})

    def __init__(self, *args):
        super().__init__(*args)
        self.repo = self.options.target_repo

    def finish(self):
        for group, licenses in self.repo.licenses.groups.items():
            if unknown_licenses := set(licenses).difference(self.repo.licenses):
                yield UnknownLicenses(group, sorted(unknown_licenses))


class PotentialLocalUse(results.Info):
    """Global USE flag is a potential local USE flag."""

    def __init__(self, flag, pkgs):
        super().__init__()
        self.flag = flag
        self.pkgs = tuple(pkgs)

    @property
    def desc(self):
        s = pluralism(self.pkgs)
        pkgs = ", ".join(self.pkgs)
        return (
            f"global USE flag {self.flag!r} is a potential local, "
            f"used by {len(self.pkgs)} package{s}: {pkgs}"
        )


class UnusedGlobalUse(results.Warning):
    """Unused use.desc flag(s)."""

    def __init__(self, flags):
        super().__init__()
        self.flags = tuple(flags)

    @property
    def desc(self):
        s = pluralism(self.flags)
        flags = ", ".join(self.flags)
        return f"use.desc unused flag{s}: {flags}"


class UnusedGlobalUseExpand(results.Warning):
    """Unused global USE_EXPAND flag(s)."""

    def __init__(self, flags):
        super().__init__()
        self.flags = tuple(flags)

    @property
    def desc(self):
        s = pluralism(self.flags)
        flags = ", ".join(self.flags)
        return f"unused flag{s}: {flags}"


class PotentialGlobalUse(results.Info):
    """Local USE flag is a potential global USE flag."""

    def __init__(self, flag, pkgs):
        super().__init__()
        self.flag = flag
        self.pkgs = tuple(pkgs)

    @property
    def desc(self):
        return (
            f"local USE flag {self.flag!r} is a potential global "
            f"used by {len(self.pkgs)} packages: {', '.join(self.pkgs)}"
        )


def _dfs(graph, start, visited=None):
    if visited is None:
        visited = set()
    visited.add(start)
    for node in graph[start] - visited:
        _dfs(graph, node, visited)
    return visited


class GlobalUseCheck(RepoCheck):
    """Check global USE and USE_EXPAND flags for various issues."""

    _source = (sources.RepositoryRepoSource, (), (("source", sources.PackageRepoSource),))
    known_results = frozenset(
        {
            PotentialLocalUse,
            PotentialGlobalUse,
            UnusedGlobalUse,
            UnusedGlobalUseExpand,
        }
    )

    def __init__(self, *args):
        super().__init__(*args)
        self.global_flag_usage = defaultdict(set)
        self.repo = self.options.target_repo

    def feed(self, pkgs):
        # ignore bad XML, it will be caught by metadata.xml checks
        local_use = set(pkgs[0].local_use.keys())
        for pkg in pkgs:
            for flag in pkg.iuse_stripped.difference(local_use):
                self.global_flag_usage[flag].add(pkg.unversioned_atom)
        yield from ()

    @staticmethod
    def _similar_flags(pkgs):
        """Yield groups of packages with similar local USE flag descriptions."""
        # calculate USE flag description difference ratios
        diffs = {}
        for i, (_i_pkg, i_desc) in enumerate(pkgs):
            for j, (_j_pkg, j_desc) in enumerate(pkgs[i + 1 :]):
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
        repo_global_use = {flag for matcher, (flag, desc) in self.repo.config.use_desc}
        repo_global_use_expand = {
            flag
            for use_expand in self.repo.config.use_expand_desc.values()
            for flag, desc in use_expand
        }
        repo_local_use = self.repo.config.use_local_desc
        unused_global_use = []
        unused_global_use_expand = []
        potential_locals = []

        for flag in repo_global_use:
            pkgs = self.global_flag_usage[flag]
            if not pkgs:
                unused_global_use.append(flag)
            elif len(pkgs) < 5:
                potential_locals.append((flag, pkgs))

        for flag in repo_global_use_expand:
            if not self.global_flag_usage[flag]:
                unused_global_use_expand.append(flag)

        if unused_global_use:
            yield UnusedGlobalUse(sorted(unused_global_use))
        if unused_global_use_expand:
            yield UnusedGlobalUseExpand(sorted(unused_global_use_expand))
        for flag, pkgs in sorted(potential_locals, key=lambda x: len(x[1])):
            pkgs = sorted(map(str, pkgs))
            yield PotentialLocalUse(flag, pkgs)

        local_use = defaultdict(list)
        for pkg, (flag, desc) in repo_local_use:
            if flag not in repo_global_use:
                local_use[flag].append((pkg, desc))

        potential_globals = []
        for flag, pkgs in sorted((k, v) for k, v in local_use.items() if len(v) >= 5):
            for matching_pkgs in self._similar_flags(pkgs):
                potential_globals.append((flag, matching_pkgs))

        for flag, pkgs in sorted(potential_globals, key=lambda x: len(x[1]), reverse=True):
            pkgs = sorted(map(str, pkgs))
            yield PotentialGlobalUse(flag, pkgs)


class MissingChksum(results.VersionResult, results.Warning):
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
            f"{', '.join(self.missing)}; has chksums: {', '.join(self.existing)}"
        )


class DeprecatedChksum(results.VersionResult, results.Warning):
    """A file in the chksum data does not use modern checksum set."""

    def __init__(self, filename, deprecated, **kwargs):
        super().__init__(**kwargs)
        self.filename = filename
        self.deprecated = tuple(deprecated)

    @property
    def desc(self):
        s = pluralism(self.deprecated)
        deprecated = ", ".join(self.deprecated)
        return f"{self.filename!r} has deprecated checksum{s}: {deprecated}"


class MissingManifest(results.VersionResult, results.Error):
    """SRC_URI targets missing from Manifest file."""

    def __init__(self, files, **kwargs):
        super().__init__(**kwargs)
        self.files = tuple(files)

    @property
    def desc(self):
        s = pluralism(self.files)
        files = ", ".join(self.files)
        return f"distfile{s} missing from Manifest: [ {files} ]"


class UnknownManifest(results.PackageResult, results.Warning):
    """Manifest entries not matching any SRC_URI targets."""

    def __init__(self, files, **kwargs):
        super().__init__(**kwargs)
        self.files = tuple(files)

    @property
    def desc(self):
        s = pluralism(self.files)
        files = ", ".join(self.files)
        return f"unknown distfile{s} in Manifest: [ {files} ]"


class UnnecessaryManifest(results.PackageResult, results.Warning):
    """Manifest entries for non-DIST targets on a repo with thin manifests enabled."""

    def __init__(self, files, **kwargs):
        super().__init__(**kwargs)
        self.files = tuple(files)

    @property
    def desc(self):
        s = pluralism(self.files)
        files = ", ".join(self.files)
        return f"unnecessary file{s} in Manifest: [ {files} ]"


class InvalidManifest(results.MetadataError, results.PackageResult):
    """Package's Manifest file is invalid."""

    attr = "manifest"


class DeprecatedManifestHash(results.PackageResult, results.Warning):
    """Manifest uses deprecated hashes.

    The package uses deprecated hash types in its Manifest file.
    """

    def __init__(self, hashes, **kwargs):
        super().__init__(**kwargs)
        self.hashes = tuple(hashes)

    @property
    def desc(self):
        s = pluralism(self.hashes)
        hashes = ", ".join(self.hashes)
        return f"defines deprecated manifest hash types{s}: [ {hashes} ]"


class ManifestCheck(Check):
    """Manifest related checks.

    Verify that the Manifest file exists, doesn't have missing or
    extraneous entries, and that the required hashes are in use.
    """

    required_addons = (addons.UseAddon,)
    _source = sources.PackageRepoSource
    known_results = frozenset(
        {
            MissingChksum,
            MissingManifest,
            UnknownManifest,
            UnnecessaryManifest,
            DeprecatedChksum,
            InvalidManifest,
            DeprecatedManifestHash,
        }
    )

    def __init__(self, *args, use_addon: addons.UseAddon):
        super().__init__(*args)
        repo = self.options.target_repo
        self.preferred_checksums = frozenset(
            repo.config.manifests.hashes if hasattr(repo, "config") else ()
        )
        self.required_checksums = frozenset(
            repo.config.manifests.required_hashes if hasattr(repo, "config") else ()
        )
        self.iuse_filter = use_addon.get_filter("fetchables")

    def feed(self, pkgset):
        pkg_manifest: Manifest = pkgset[0].manifest
        pkg_manifest.allow_missing = True
        manifest_distfiles = set(pkg_manifest.distfiles.keys())
        seen = set()
        for pkg in pkgset:
            pkg.release_cached_data()
            fetchables, _ = self.iuse_filter(
                (fetch.fetchable,),
                pkg,
                pkg.generate_fetchables(allow_missing_checksums=True, ignore_unknown_mirrors=True),
            )
            fetchables = set(fetchables)
            pkg.release_cached_data()

            fetchable_files = {f.filename for f in fetchables}
            missing_manifests = fetchable_files.difference(manifest_distfiles)
            if missing_manifests:
                yield MissingManifest(sorted(missing_manifests), pkg=pkg)

            for f_inst in fetchables:
                if f_inst.filename in seen:
                    continue
                missing = self.required_checksums.difference(f_inst.chksums)
                if f_inst.filename not in missing_manifests and missing:
                    yield MissingChksum(
                        f_inst.filename, sorted(missing), sorted(f_inst.chksums), pkg=pkg
                    )
                elif f_inst.chksums:
                    if deprecated := frozenset(f_inst.chksums).difference(self.preferred_checksums):
                        yield DeprecatedChksum(f_inst.filename, sorted(deprecated), pkg=pkg)
                seen.add(f_inst.filename)

        if pkg_manifest.thin:
            unnecessary_manifests = set()
            for attr in ("aux_files", "ebuilds", "misc"):
                unnecessary_manifests.update(getattr(pkg_manifest, attr, ()))
            if unnecessary_manifests:
                yield UnnecessaryManifest(sorted(unnecessary_manifests), pkg=pkgset[0])

        if unknown_manifests := manifest_distfiles.difference(seen):
            yield UnknownManifest(sorted(unknown_manifests), pkg=pkgset[0])

        used_hashes = frozenset().union(*pkg_manifest.distfiles.values())
        if deprecated_hashes := DEPRECATED_HASHES.intersection(used_hashes):
            yield DeprecatedManifestHash(sorted(deprecated_hashes), pkg=pkgset[0])


class ConflictingChksums(results.VersionResult, results.Error):
    """Checksum conflict detected between two files."""

    def __init__(self, filename, chksums, pkgs, **kwargs):
        super().__init__(**kwargs)
        self.filename = filename
        self.chksums = tuple(chksums)
        self.pkgs = tuple(pkgs)

    @property
    def desc(self):
        s = pluralism(self.chksums)
        chksums = ", ".join(self.chksums)
        pkgs_s = pluralism(self.pkgs)
        pkgs = ", ".join(self.pkgs)
        return (
            f"distfile {self.filename!r} has different checksum{s} "
            f"({chksums}) for package{pkgs_s}: {pkgs}"
        )


class MatchingChksums(results.VersionResult, results.Warning):
    """Two distfiles share the same checksums but use different names."""

    def __init__(self, filename, orig_file, orig_pkg, **kwargs):
        super().__init__(**kwargs)
        self.filename = filename
        self.orig_file = orig_file
        self.orig_pkg = orig_pkg

    @property
    def desc(self):
        msg = f"distfile {self.filename!r} matches checksums for {self.orig_file!r}"
        if f"{self.category}/{self.package}" != self.orig_pkg:
            msg += f" from {self.orig_pkg}"
        return msg


class ManifestCollisionCheck(Check):
    """Search Manifest entries for different types of distfile collisions.

    In particular, search for matching filenames with different checksums and
    different filenames with matching checksums.
    """

    _source = (sources.RepositoryRepoSource, (), (("source", sources.PackageRepoSource),))
    known_results = frozenset({ConflictingChksums, MatchingChksums})

    def __init__(self, *args):
        super().__init__(*args)
        self.seen_files = {}
        self.seen_chksums = {}
        # ignore go.mod false positives (issue #228)
        self._ignored_files_re = re.compile(r"^.*%2F@v.*\.mod$")

    def _conflicts(self, pkg):
        """Check for similarly named distfiles with different checksums."""
        for filename, chksums in pkg.manifest.distfiles.items():
            existing = self.seen_files.get(filename)
            if existing is None:
                self.seen_files[filename] = ([pkg.key], dict(chksums.items()))
                continue
            seen_pkgs, seen_chksums = existing
            conflicting_chksums = []
            for chf_type, value in seen_chksums.items():
                our_value = chksums.get(chf_type)
                if our_value is not None and our_value != value:
                    conflicting_chksums.append(chf_type)
            if conflicting_chksums:
                pkgs = map(str, sorted(seen_pkgs))
                yield ConflictingChksums(filename, sorted(conflicting_chksums), pkgs, pkg=pkg)
            else:
                seen_chksums.update(chksums)
                seen_pkgs.append(pkg.key)

    def _matching(self, pkg):
        """Check for distfiles with matching checksums and different names."""
        for filename, chksums in pkg.manifest.distfiles.items():
            key = tuple(chksums.values())
            existing = self.seen_chksums.get(key)
            if existing is None:
                self.seen_chksums[key] = (pkg.key, filename)
                continue
            seen_pkg, seen_file = existing
            if seen_file == filename or self._ignored_files_re.match(filename):
                continue
            yield MatchingChksums(filename, seen_file, seen_pkg, pkg=pkg)

    def feed(self, pkgs):
        pkg = pkgs[0]
        yield from self._conflicts(pkg)
        yield from self._matching(pkg)


class EmptyProject(results.Warning):
    """A project has no developers."""

    def __init__(self, project):
        super().__init__()
        self.project = str(project)

    @property
    def desc(self):
        return f"Project has no members: {self.project}"


class ProjectMetadataCheck(RepoCheck):
    """Check projects.xml for issues."""

    _source = (sources.EmptySource, (base.repo_scope,))
    known_results = frozenset({EmptyProject})

    def __init__(self, *args):
        super().__init__(*args)
        self.repo = self.options.target_repo

    def finish(self):
        for project in self.repo.projects_xml.projects.values():
            if not project.recursive_members:
                yield EmptyProject(project)


class DeprecatedRepoHash(results.Warning):
    """Repositories ``manifest-hashes`` defines deprecated hashes.

    The repository defines deprecated hashes in ``manifest-hashes``.
    """

    def __init__(self, hashes):
        super().__init__()
        self.hashes = tuple(hashes)

    @property
    def desc(self):
        s = pluralism(self.hashes)
        hashes = ", ".join(self.hashes)
        return f"defines deprecated manifest-hash{s}: [ {hashes} ]"


class RepoManifestHashCheck(RepoCheck):
    """Check ``manifest-hashes`` config for issues."""

    _source = (sources.EmptySource, (base.repo_scope,))
    known_results = frozenset({DeprecatedRepoHash})

    def __init__(self, *args):
        super().__init__(*args)
        self.repo = self.options.target_repo

    def finish(self):
        if deprecated_hashes := DEPRECATED_HASHES.intersection(self.repo.config.manifests.hashes):
            yield DeprecatedRepoHash(sorted(deprecated_hashes))
