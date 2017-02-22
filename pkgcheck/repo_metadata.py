# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: BSD/GPL2

from itertools import ifilterfalse, chain, groupby
from operator import attrgetter, itemgetter

from pkgcore.fetch import fetchable
from snakeoil import mappings
from snakeoil.demandload import demandload

from pkgcheck import base, addons

demandload(
    'os',
    'snakeoil.osutils:listdir_dirs,listdir_files,pjoin',
    'snakeoil.sequences:iflatten_instance',
    'snakeoil.strings:pluralism',
    'pkgcore:fetch',
    'pkgcore.ebuild.profiles:ProfileStack',
)


class UnusedGlobalFlags(base.Warning):
    """Unused use.desc flag(s)."""

    __slots__ = ("flags",)

    threshold = base.repository_feed

    def __init__(self, flags):
        super(UnusedGlobalFlags, self).__init__()
        # tricky, but it works; atoms have the same attrs
        self.flags = tuple(sorted(flags))

    @property
    def short_desc(self):
        return "use.desc unused flag%s: %s" % (
            pluralism(self.flags), ', '.join(self.flags))


class UnusedGlobalFlagsCheck(base.Template):
    """Check for unused use.desc entries."""

    feed_type = base.versioned_feed
    scope = base.repository_scope
    required_addons = (addons.UseAddon,)
    known_results = (UnusedGlobalFlags,) + addons.UseAddon.known_results

    def __init__(self, options, iuse_handler):
        base.Template.__init__(self, options)
        self.flags = None
        self.iuse_handler = iuse_handler

    def start(self):
        if not self.options.target_repo.masters:
            self.flags = set(self.iuse_handler.global_iuse - self.iuse_handler.unstated_iuse)

    def feed(self, pkg, reporter):
        if self.flags:
            self.flags.difference_update(pkg.iuse_stripped)

    def finish(self, reporter):
        if self.flags:
            reporter.add_report(UnusedGlobalFlags(self.flags))
            self.flags.clear()


class UnusedLicenses(base.Warning):
    """Unused license(s) detected."""

    __slots__ = ("licenses",)

    threshold = base.repository_feed

    def __init__(self, licenses):
        super(UnusedLicenses, self).__init__()
        self.licenses = tuple(sorted(licenses))

    @property
    def short_desc(self):
        return "unused license%s: %s" % (
            pluralism(self.licenses), ', '.join(self.licenses))


class UnusedLicensesCheck(base.Template):
    """Check for unused license files."""

    feed_type = base.versioned_feed
    scope = base.repository_scope
    known_results = (UnusedLicenses,)

    def __init__(self, options):
        base.Template.__init__(self, options)
        self.licenses = None

    def start(self):
        master_licenses = set()
        for repo in self.options.target_repo.masters:
            master_licenses.update(repo.licenses)
        self.licenses = set(self.options.target_repo.licenses) - master_licenses

    def feed(self, pkg, reporter):
        self.licenses.difference_update(iflatten_instance(pkg.license))

    def finish(self, reporter):
        if self.licenses:
            reporter.add_report(UnusedLicenses(self.licenses))
        self.licenses = None


class UnusedMirrors(base.Warning):
    """Unused mirrors detected."""

    __slots__ = ("mirrors",)

    threshold = base.repository_feed

    def __init__(self, mirrors):
        super(UnusedMirrors, self).__init__()
        self.mirrors = tuple(sorted(mirrors))

    @property
    def short_desc(self):
        return ', '.join(self.mirrors)


class UnusedMirrorsCheck(base.Template):
    """Check for unused mirrors."""

    required_addons = (addons.UseAddon,)
    feed_type = base.versioned_feed
    scope = base.repository_scope
    known_results = (UnusedMirrors,) + addons.UseAddon.known_results

    def __init__(self, options, iuse_handler):
        base.Template.__init__(self, options)
        self.mirrors = None
        self.iuse_filter = iuse_handler.get_filter('fetchables')

    def start(self):
        repo = self.options.target_repo
        repo_mirrors = set(repo.mirrors.iterkeys())
        master_mirrors = set(x for master in repo.masters for x in master.mirrors.iterkeys())
        self.mirrors = repo_mirrors.difference(master_mirrors)

    def feed(self, pkg, reporter):
        if self.mirrors:
            mirrors = []
            for f in self.iuse_filter((fetchable,), pkg, pkg.fetchables, reporter):
                for m in f.uri.visit_mirrors(treat_default_as_mirror=False):
                    mirrors.append(m[0].mirror_name)
            self.mirrors.difference_update(mirrors)

    def finish(self, reporter):
        if self.mirrors:
            reporter.add_report(UnusedMirrors(self.mirrors))
        self.mirrors = None


class UnusedEclasses(base.Warning):
    """Unused eclasses detected."""

    __slots__ = ("eclasses",)

    threshold = base.repository_feed

    def __init__(self, eclasses):
        super(UnusedEclasses, self).__init__()
        self.eclasses = tuple(sorted(eclasses))

    @property
    def short_desc(self):
        return ', '.join(self.eclasses)


class UnusedEclassesCheck(base.Template):
    """Check for unused eclasses."""

    feed_type = base.versioned_feed
    scope = base.repository_scope
    known_results = (UnusedEclasses,)

    def __init__(self, options):
        base.Template.__init__(self, options)
        self.eclasses = None

    def start(self):
        self.eclasses = {e for e in self.options.target_repo.eclass_cache.eclasses.iterkeys()}

    def feed(self, pkg, reporter):
        self.eclasses.difference_update(pkg.inherited)

    def finish(self, reporter):
        if self.eclasses:
            reporter.add_report(UnusedEclasses(self.eclasses))
        self.eclasses = None


class UnusedProfileDirs(base.Warning):
    """Unused profile directories detected."""

    __slots__ = ("dirs",)

    threshold = base.repository_feed

    def __init__(self, dirs):
        super(UnusedProfileDirs, self).__init__()
        self.dirs = sorted(dirs)

    @property
    def short_desc(self):
        return "[ %s ]" % ', '.join(self.dirs)


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


class UnknownCategories(base.Warning):
    """Category directories that aren't listed in a repo's categories.

    Or the categories of the repo's masters as well.
    """

    __slots__ = ("categories",)

    threshold = base.repository_feed

    def __init__(self, categories):
        super(UnknownCategories, self).__init__()
        self.categories = categories

    @property
    def short_desc(self):
        return "[ %s ]" % ', '.join(self.categories)


class RepoProfilesReport(base.Template):
    """Scan repo for various profiles directory issues.

    Including unknown arches in profiles, arches without profiles, and unknown
    categories.
    """

    required_addons = (addons.ProfileAddon,)
    feed_type = base.repository_feed
    scope = base.repository_scope
    known_results = (
        UnknownProfileArches, ArchesWithoutProfiles, UnusedProfileDirs,
        NonexistentProfilePath, UnknownProfileStatus, UnknownCategories)

    def __init__(self, options, profile_filters):
        base.Template.__init__(self, options)
        self.arches = options.target_repo.config.known_arches
        self.profiles = options.target_repo.config.arch_profiles.itervalues()
        self.repo = options.target_repo
        self.profiles_dir = pjoin(self.repo.location, 'profiles')

    def feed(self, pkg, reporter):
        pass

    def finish(self, reporter):
        category_dirs = set(ifilterfalse(
            self.repo.false_categories.__contains__,
            (x for x in listdir_dirs(self.repo.location) if x[0] != '.')))
        unknown_categories = category_dirs.difference(self.repo.categories)
        if unknown_categories:
            reporter.add_report(UnknownCategories(unknown_categories))

        unknown_arches = self.repo.config.profiles.arches().difference(self.arches)
        arches_without_profiles = self.arches.difference(self.repo.config.profiles.arches())

        if unknown_arches:
            reporter.add_report(UnknownProfileArches(unknown_arches))
        if arches_without_profiles:
            reporter.add_report(ArchesWithoutProfiles(arches_without_profiles))

        non_profile_dirs = {'desc', 'updates'}
        root_profile_dirs = {'embedded'}
        available_profile_dirs = set()
        for root, _dirs, _files in os.walk(self.profiles_dir):
            # skip deprecated profiles
            if not os.path.exists(pjoin(root, 'deprecated')):
                d = root[len(self.profiles_dir):].lstrip('/')
                if d:
                    available_profile_dirs.add(d)
        available_profile_dirs -= non_profile_dirs | root_profile_dirs

        def parents(path):
            """Yield all directory path parents excluding the root directory.

            Example:
            >>> list(parents('/root/foo/bar/baz'))
            ['root/foo/bar', 'root/foo', 'root']
            """
            path = os.path.normpath(path.strip('/'))
            while path:
                yield path
                dirname, _basename = os.path.split(path)
                path = dirname.rstrip('/')

        seen_profile_dirs = set()
        profile_status = set()
        for path, status in chain.from_iterable(self.profiles):
            for x in ProfileStack(pjoin(self.profiles_dir, path)).stack:
                seen_profile_dirs.update(parents(x.path[len(self.profiles_dir):]))
            if not os.path.exists(pjoin(self.profiles_dir, path)):
                reporter.add_report(NonexistentProfilePath(path))
            profile_status.add(status)

        unused_profile_dirs = available_profile_dirs - seen_profile_dirs
        if unused_profile_dirs:
            reporter.add_report(UnusedProfileDirs(unused_profile_dirs))

        if self.repo.repo_name == 'gentoo':
            accepted_status = ('stable', 'dev', 'exp')
            unknown_status = profile_status.difference(accepted_status)
            if unknown_status:
                reporter.add_report(UnknownProfileStatus(unknown_status))


class UnknownLicenses(base.Warning):
    """License(s) listed in license group(s) that don't exist."""

    __slots__ = ("group", "licenses")

    threshold = base.repository_feed

    def __init__(self, group, licenses):
        super(UnknownLicenses, self).__init__()
        self.group = group
        self.licenses = licenses

    @property
    def short_desc(self):
        return "license group %r has unknown license%s: [ %s ]" % (
            self.group, pluralism(self.licenses), ', '.join(self.licenses))


class LicenseGroupsCheck(base.Template):
    """Scan license groups for unknown licenses."""

    feed_type = base.repository_feed
    scope = base.repository_scope
    known_results = (UnknownLicenses,)

    def __init__(self, options):
        base.Template.__init__(self, options)
        self.repo = options.target_repo

    def feed(self, pkg, reporter):
        pass

    def finish(self, reporter):
        for group, licenses in self.repo.licenses.groups.iteritems():
            unknown_licenses = set(licenses).difference(self.repo.licenses)
            if unknown_licenses:
                reporter.add_report(UnknownLicenses(group, unknown_licenses))


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
            pluralism(self.files), ', '.join(sorted(self.files)),)


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
            pluralism(self.files), ', '.join(sorted(self.files)),)


class UnnecessaryManifest(base.Warning):
    """Manifest entries for non-DIST targets on a repo with thin manifests enabled."""

    __slots__ = ("category", "package", "files")
    threshold = base.package_feed

    def __init__(self, pkg, files):
        super(UnnecessaryManifest, self).__init__()
        self._store_cp(pkg)
        self.files = files

    @property
    def short_desc(self):
        return "unnecessary file%s in Manifest: [ %s ]" % (
            pluralism(self.files), ', '.join(sorted(self.files)),)


class ManifestReport(base.Template):
    """Manifest related checks.

    Verify that the Manifest file exists, doesn't have missing or
    extraneous entries, and that the required hashes are in use.
    """

    required_addons = (addons.UseAddon,)
    feed_type = base.package_feed
    known_results = (MissingChksum, MissingManifest, UnknownManifest, UnnecessaryManifest) + \
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
        for repo, pkgset in groupby(full_pkgset, self.repo_grabber):
            required_checksums = self.required_checksums[repo]
            pkgset = list(pkgset)
            pkg_manifest = pkgset[0].manifest
            manifest_distfiles = set(pkg_manifest.distfiles.iterkeys())
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
                missing_manifests = fetchable_files.difference(manifest_distfiles)
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

            if pkg_manifest.thin:
                unnecessary_manifests = []
                for attr in ('aux_files', 'ebuilds', 'misc'):
                    unnecessary_manifests.extend(getattr(pkg_manifest, attr, []))
                if unnecessary_manifests:
                    reporter.add_report(UnnecessaryManifest(pkgset[0], unnecessary_manifests))

            unknown_manifests = manifest_distfiles.difference(seen)
            if unknown_manifests:
                reporter.add_report(UnknownManifest(pkgset[0], unknown_manifests))
