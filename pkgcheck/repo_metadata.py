# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: BSD/GPL2

import itertools
from operator import attrgetter, itemgetter

from pkgcore.ebuild.repository import SlavedTree
from snakeoil import mappings
from snakeoil.demandload import demandload

from pkgcheck import base, addons

demandload(
    'os',
    'snakeoil.osutils:listdir_dirs,listdir_files,pjoin',
    'snakeoil.sequences:iflatten_instance',
    'pkgcore:fetch',
)


class UnusedGlobalFlagsResult(base.Warning):
    """unused use.desc flag(s)"""

    __slots__ = ("flags",)

    threshold = base.repository_feed

    def __init__(self, flags):
        super(UnusedGlobalFlagsResult, self).__init__()
        # tricky, but it works; atoms have the same attrs
        self.flags = tuple(sorted(flags))

    @property
    def short_desc(self):
        return "use.desc unused flag%s: %s" % (
            's'[len(self.flags) == 1:], ', '.join(self.flags))


class UnusedGlobalFlags(base.Template):
    """check for unused use.desc entries"""

    feed_type = base.versioned_feed
    scope = base.repository_scope
    required_addons = (addons.UseAddon,)
    known_results = (UnusedGlobalFlagsResult,) + addons.UseAddon.known_results

    def __init__(self, options, iuse_handler):
        base.Template.__init__(self, options)
        self.flags = None
        self.iuse_handler = iuse_handler

    def start(self):
        if not isinstance(self.options.target_repo, SlavedTree):
            self.flags = set(self.iuse_handler.global_iuse - self.iuse_handler.unstated_iuse)

    def feed(self, pkg, reporter):
        if self.flags:
            self.flags.difference_update(pkg.iuse_stripped)

    def finish(self, reporter):
        if self.flags:
            reporter.add_report(UnusedGlobalFlagsResult(self.flags))
            self.flags.clear()


class UnusedLicenseReport(base.Warning):
    """unused license(s) detected"""

    __slots__ = ("licenses",)

    threshold = base.repository_feed

    def __init__(self, licenses):
        super(UnusedLicenseReport, self).__init__()
        self.licenses = tuple(sorted(licenses))

    @property
    def short_desc(self):
        return "unused license%s: %s" % (
            's'[len(self.licenses) == 1:], ', '.join(self.licenses))


class UnusedLicense(base.Template):
    """unused license file(s) check"""

    feed_type = base.versioned_feed
    scope = base.repository_scope
    required_addons = (addons.LicenseAddon,)
    known_results = (UnusedLicenseReport,)

    def __init__(self, options, licenses):
        base.Template.__init__(self, options)
        self.licenses = None

    def start(self):
        self.licenses = set()
        if isinstance(self.options.target_repo, SlavedTree):
            if 'licenses' in listdir_dirs(self.options.target_repo.location):
                self.licenses.update(listdir_files(pjoin(self.options.target_repo.location, "licenses")))
        else:
            for license_dir in self.options.license_dirs:
                self.licenses.update(listdir_files(license_dir))

    def feed(self, pkg, reporter):
        self.licenses.difference_update(iflatten_instance(pkg.license))

    def finish(self, reporter):
        if self.licenses:
            reporter.add_report(UnusedLicenseReport(self.licenses))
        self.licenses = None


class UnknownProfileArches(base.Warning):
    """Unknown arches used in profiles."""

    __slots__ = ("arches",)

    threshold = base.repository_feed

    def __init__(self, arches):
        super(UnknownProfileArches, self).__init__()
        self.arches = arches

    @property
    def short_desc(self):
        return "[ %s ]" % ', '.join(self.arches)


class ArchesWithoutProfiles(base.Warning):
    """Arches without corresponding profile listings."""

    __slots__ = ("arches",)

    threshold = base.repository_feed

    def __init__(self, arches):
        super(ArchesWithoutProfiles, self).__init__()
        self.arches = arches

    @property
    def short_desc(self):
        return "[ %s ]" % ', '.join(self.arches)


class UnknownProfileStatus(base.Warning):
    """Unknown status used for profiles."""

    __slots__ = ("status",)

    threshold = base.repository_feed

    def __init__(self, status):
        super(UnknownProfileStatus, self).__init__()
        self.status = status

    @property
    def short_desc(self):
        return "[ %s ]" % ', '.join(self.status)


class NonexistentProfilePath(base.Warning):
    """Specified profile path doesn't exist."""

    __slots__ = ("path",)

    threshold = base.repository_feed

    def __init__(self, path):
        super(NonexistentProfilePath, self).__init__()
        self.path = path

    @property
    def short_desc(self):
        return self.path


class RepoProfilesReport(base.Template):
    """Scan for unknown arches in profiles and arches without profiles."""

    feed_type = base.repository_feed
    known_results = (
        UnknownProfileArches, ArchesWithoutProfiles,
        NonexistentProfilePath, UnknownProfileStatus)

    def __init__(self, options):
        base.Template.__init__(self, options)
        self.arches = options.target_repo.config.known_arches
        self.profiles = options.target_repo.config.profiles.arch_profiles
        self.repo = options.target_repo

    def feed(self, pkg, reporter):
        pass

    def finish(self, reporter):
        profile_arches = set(self.profiles.iterkeys())
        unknown_arches = profile_arches.difference(self.arches)
        arches_without_profiles = self.arches.difference(profile_arches)

        if unknown_arches:
            reporter.add_report(UnknownProfileArches(unknown_arches))
        if arches_without_profiles:
            reporter.add_report(ArchesWithoutProfiles(arches_without_profiles))

        profile_status = set()
        for path, status in itertools.chain.from_iterable(self.profiles.itervalues()):
            if not os.path.exists(pjoin(self.repo.location, 'profiles', path)):
                reporter.add_report(NonexistentProfilePath(path))
            profile_status.add(status)

        if self.repo.repo_id == 'gentoo':
            accepted_status = ('stable', 'dev', 'exp')
            unknown_status = profile_status.difference(accepted_status)
            if unknown_status:
                reporter.add_report(UnknownProfileStatus(unknown_status))

def reformat_chksums(iterable):
    for chf, val1, val2 in iterable:
        if chf == "size":
            yield chf, val1, val2
        else:
            yield chf, "%x" % val1, "%x" % val2


class ConflictingChksums(base.Error):
    """checksum conflict detected between two files"""

    __slots__ = ("category", "package", "version",
                 "filename", "chksums", "others")

    threshold = base.versioned_feed

    _sorter = staticmethod(itemgetter(0))

    def __init__(self, pkg, filename, chksums, others):
        super(ConflictingChksums, self).__init__()
        self._store_cpv(pkg)
        self.filename = filename
        self.chksums = tuple(sorted(reformat_chksums(chksums),
                                    key=self._sorter))
        self.others = tuple(sorted(others))

    @property
    def short_desc(self):
        return "conflicts with (%s) for file %s chksum %s" % (
            ', '.join(self.others), self.filename, self.chksums)


class MissingChksum(base.Warning):
    """a file in the chksum data lacks required checksums"""

    threshold = base.versioned_feed
    __slots__ = ('category', 'package', 'version', 'filename', 'missing',
                 'existing')

    def __init__(self, pkg, filename, missing, existing):
        super(MissingChksum, self).__init__()
        self._store_cpv(pkg)
        self.filename, self.missing = filename, tuple(sorted(missing))
        self.existing = tuple(sorted(existing))

    @property
    def short_desc(self):
        return '"%s" missing required chksums: %s; has chksums: %s' % \
            (self.filename, ', '.join(self.missing), ', '.join(self.existing))


class MissingManifest(base.Error):
    """SRC_URI targets missing from Manifest file"""

    __slots__ = ("category", "package", "version", "files")
    threshold = base.versioned_feed

    def __init__(self, pkg, files):
        super(MissingManifest, self).__init__()
        self._store_cpv(pkg)
        self.files = files

    @property
    def short_desc(self):
        return "distfile%s missing from Manifest: [ %s ]" % (
            's'[len(self.files) == 1:], ', '.join(sorted(self.files)),)


class UnknownManifest(base.Warning):
    """Manifest entries not matching any SRC_URI targets"""

    __slots__ = ("category", "package", "files")
    threshold = base.package_feed

    def __init__(self, pkg, files):
        super(UnknownManifest, self).__init__()
        self._store_cp(pkg)
        self.files = files

    @property
    def short_desc(self):
        return "unknown distfile%s in Manifest: [ %s ]" % (
            's'[len(self.files) == 1:], ', '.join(sorted(self.files)),)


class ManifestReport(base.Template):
    """Manifest related checks.

    Verify that the Manifest file exists, doesn't have missing or
    extraneous entries, and that the required hashes are in use.
    """

    required_addons = (addons.UseAddon,)
    feed_type = base.package_feed
    known_results = (MissingChksum, MissingManifest, UnknownManifest) + \
        addons.UseAddon.known_results

    repo_grabber = attrgetter("repo")

    def __init__(self, options, iuse_handler):
        base.Template.__init__(self, options)
        self.required_checksums = mappings.defaultdictkey(
            lambda repo: frozenset(repo.config.manifests.hashes if hasattr(repo, 'config') else ()))
        self.seen_checksums = {}
        self.iuse_filter = iuse_handler.get_filter('fetchables')

    def feed(self, full_pkgset, reporter):
        # sort it by repo.
        for repo, pkgset in itertools.groupby(full_pkgset, self.repo_grabber):
            required_checksums = self.required_checksums[repo]
            pkgset = list(pkgset)
            manifests = set(pkgset[0].manifest.distfiles.iterkeys())
            seen = set()
            for pkg in pkgset:
                pkg.release_cached_data()
                fetchables = set(self.iuse_filter(
                    (fetch.fetchable,), pkg,
                    pkg._get_attr['fetchables'](
                        pkg, allow_missing_checksums=True, ignore_unknown_mirrors=True),
                    reporter))
                pkg.release_cached_data()

                fetchable_files = set(f.filename for f in fetchables)
                missing_manifests = fetchable_files.difference(manifests)
                if missing_manifests:
                    reporter.add_report(MissingManifest(pkg, missing_manifests))

                for f_inst in fetchables:
                    if f_inst.filename in seen:
                        continue
                    missing = required_checksums.difference(f_inst.chksums)
                    if f_inst.filename not in missing_manifests and missing:
                        reporter.add_report(
                            MissingChksum(pkg, f_inst.filename, missing,
                                          f_inst.chksums))
                    seen.add(f_inst.filename)
                    existing = self.seen_checksums.get(f_inst.filename)
                    if existing is None:
                        existing = ([pkg], dict(f_inst.chksums.iteritems()))
                        continue
                    seen_pkgs, seen_chksums = existing
                    for chf_type, value in seen_chksums.iteritems():
                        our_value = f_inst.chksums.get(chf_type)
                        if our_value is not None and our_value != value:
                            reporter.add_result(ConflictingChksums(
                                pkg, f_inst.filename, f_inst.chksums, seen_chksums))
                            break
                    else:
                        seen_chksums.update(f_inst.chksums)
                        seen_pkgs.append(pkg)

            unknown_manifests = manifests.difference(seen)
            if unknown_manifests:
                reporter.add_report(UnknownManifest(pkgset[0], unknown_manifests))
