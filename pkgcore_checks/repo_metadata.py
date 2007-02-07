# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: GPL2

from pkgcore_checks import base, util, addons
from pkgcore.ebuild.repository import SlavedTree
from pkgcore.util.osutils import listdir_dirs
import os.path
from pkgcore.util.demandload import demandload
import operator, itertools
from pkgcore.chksum.errors import MissingChksum

demandload(globals(), "pkgcore.util.xml:escape "
    "pkgcore.util.osutils:listdir_files,pjoin "
    "pkgcore.util.lists:iflatten_instance "
    "pkgcore.fetch:fetchable "
    "pkgcore.ebuild:misc ")


class UnusedLocalFlagsResult(base.Result):
    
    """
    unused use.local.desc flag(s)
    """
    
    __slots__ = ("category", "package", "flags")

    threshold = base.package_feed

    def __init__(self, pkg, flags):
        base.Result.__init__(self)
        # tricky, but it works; atoms have the same attrs
        self._store_cp(pkg)
        self.flags = tuple(sorted(flags))
    
    @property
    def short_desc(self):
        return "use.local.desc unused flag(s) %s" % ', '.join(self.flags)


class UnusedLocalFlags(base.Template):

    """
    check for unused use.local.desc entries
    """

    feed_type = base.package_feed
    required_addons = (addons.UseAddon,)
    known_results = (UnusedLocalFlagsResult,) + addons.UseAddon.known_results

    def __init__(self, options, use_handler):
        base.Template.__init__(self, options)
        self.iuse_handler = use_handler

    def start(self):
        self.collapsed = misc.non_incremental_collapsed_restrict_to_data(
            self.iuse_handler.specific_iuse)

    def feed(self, pkgs, reporter):
        unused = set()
        for pkg in pkgs:
            unused.update(self.collapsed.iter_pull_data(pkg))
        for pkg in pkgs:
            unused.difference_update(pkg.iuse)
        if unused:
            reporter.add_report(UnusedLocalFlagsResult(pkg, unused))


class UnusedGlobalFlagsResult(base.Result):
    
    """
    unused use.desc flag(s)
    """
    
    __slots__ = ("flags",)

    threshold = base.repository_feed

    def __init__(self, flags):
        base.Result.__init__(self)
        # tricky, but it works; atoms have the same attrs
        self.flags = tuple(sorted(flags))
    
    @property
    def short_desc(self):
        return "use.desc unused flag(s): %s" % ', '.join(self.flags)


class UnusedGlobalFlags(base.Template):
    """
    check for unused use.desc entries
    """

    feed_type = base.versioned_feed
    scope = base.repository_scope
    required_addons = (addons.UseAddon,)
    known_results = (UnusedGlobalFlagsResult,) + addons.UseAddon.known_results

    def __init__(self, options, iuse_handler):
        base.Template.__init__(self, options)
        self.flags = None
        self.iuse_handler = iuse_handler

    def start(self):
        if not isinstance(self.options.target_repo,SlavedTree):
            self.flags = set(self.iuse_handler.global_iuse)

    def feed(self, pkg, reporter):
        if self.flags:
            self.flags.difference_update(pkg.iuse)

    def finish(self, reporter):
        if self.flags:
            reporter.add_report(UnusedGlobalFlagsResult(self.flags))
            self.flags.clear()


class UnusedLicenseReport(base.Result):
    """
    unused license(s) detected
    """
    
    __slots__ = ("licenses",)
    
    threshold = base.repository_feed
    
    def __init__(self, licenses):
        base.Result.__init__(self)
        self.licenses = tuple(sorted(licenses))

    @property
    def short_desc(self):
        return "unused license(s): %s" % ', '.join(self.licenses)


class UnusedLicense(base.Template):
    """
    unused license file(s) check
    """

    feed_type = base.versioned_feed
    scope = base.repository_scope
    required_addons = (addons.LicenseAddon,)
    known_results = (UnusedLicenseReport,)

    def __init__(self, options, licenses):
        base.Template.__init__(self, options)
        self.licenses = None

    def start(self):
        self.licenses = set()
        if isinstance(self.options.target_repo,SlavedTree):
            if 'licenses' in listdir_dirs(self.options.target_repo.location):
                self.licenses.update(listdir_files(pjoin(self.options.target_repo.location,"licenses")))
        else:
            for license_dir in self.options.license_dirs:
                self.licenses.update(listdir_files(license_dir))

    def feed(self, pkg, reporter):
        self.licenses.difference_update(iflatten_instance(pkg.license))

    def finish(self, reporter):
        if self.licenses:
            reporter.add_report(UnusedLicenseReport(self.licenses))
        self.licenses = None


def reformat_chksums(iterable):
    for chf, val1, val2 in iterable:
        if chf == "size":
            yield chf, val1, val2
        else:
            yield chf, "%x" % val1, "%x" % val2
    

class ConflictingChksums(base.Result):

    """
    checksum conflict detected between two files
    """

    __slots__ = ("category", "package", "version",
        "filename", "chksums", "others")
    
    threshold = base.versioned_feed
    
    _sorter = staticmethod(operator.itemgetter(0))
    
    def __init__(self, pkg, filename, chksums, others):
        base.Result.__init__(self)
        self._store_cpv(pkg)
        self.filename = filename
        self.chksums = tuple(sorted(reformat_chksums(chksums),
            key=self._sorter))
        self.others = tuple(sorted(others))

    @property
    def short_desc(self):
        return "conflicts with (%s) for file %s chksums %s" % (
            ', '.join(self.others), self.filename, self.chksums)


class ConflictingDigests(base.Template):
    """
    scan for conflicting digest entries; since this requires
    keeping all fetchables in memory, this can add up.
    """

    scope = base.package_scope
    feed_type = base.versioned_feed
    known_results = (ConflictingChksums,)

    def __init__(self, options):
        base.Template.__init__(self, options)
        self._fetchables = {}

    def feed(self, pkg, reporter):
        for uri in iflatten_instance(pkg.fetchables, fetchable):
            existing = self._fetchables.get(uri.filename, None)
            if existing is not None:
                reqed_chksums = existing[0]
                conflicts = []
                for chf, val in uri.chksums.iteritems():
                    oval = reqed_chksums.get(chf, None)
                    if oval is not None:
                        if oval != val:
                            conflicts.append((chf, val, oval))

                if conflicts:
                    reporter.add_report(ConflictingChksums(
                        pkg, uri.filename, conflicts, existing[1]))
                elif len(uri.chksums) > len(existing):
                    self._fetchables[uri.filename] = existing
                existing[1].append(util.get_cpvstr(pkg))
            else:
                self._fetchables[uri.filename] = \
                    (uri.chksums, [util.get_cpvstr(pkg)])

    def finish(self, reporter):
        self._fetchables.clear()


class ManifestDigestConflict(base.Result):
    """
    Manifest2 and digest file disagree
    """

    __slots__ = ("category", "package", "version", 
        "msg", "filename")


    threshold = base.versioned_feed

    def __init__(self, pkg, filename, msg):
        base.Result.__init__(self)
        self._store_cpv(pkg)
        self.filename = filename
        self.msg = msg
    
    @property
    def short_desc(self):
        return "Manifest/digest conflict for file %s: %s" % (self.filename, self.msg)


class OrphanedManifestDist(base.Result):
    """
    manifest2 has a checksum entry digest lacks
    """
    
    __slots__ = ("category", "package", "version",
        "files")

    threshold = base.versioned_feed

    def __init__(self, pkg, files):
        base.Result.__init__(self)
        self._store_cp(pkg)
        self.files = tuple(sorted(files))
    
    @property
    def short_desc(self):
        return "manifest2 knows of files %r, but digest1 doesn't" % (self.files,)


class MissingDigest(base.Result):
    """
    file lacks checksum data
    """
    
    __slots__ = ("category", "package", "version", "filename")

    threshold = base.versioned_feed

    def __init__(self, pkg, filename):
        base.Result.__init__(self)
        self._store_cp(pkg)
        self.filename = filename
    
    @property
    def short_desc(self):
        return "file %s has no checksum info" % self.filename


class ConflictManifestDigest(base.Template):

    """Scan for conflicts between the Manifest file and digest files."""

    feed_type = base.package_feed
    known_results = (ManifestDigestConflict, OrphanedManifestDist,
        MissingDigest)

    repo_grabber = operator.attrgetter("repo")

    def feed(self, full_pkgset, reporter):
        # sort it by repo.
        for repo, pkgset in itertools.groupby(full_pkgset, self.repo_grabber):
            pkgset = list(pkgset)
            manifest = pkgset[0].manifest
            if manifest.version == 1:
                continue
            f = getattr(repo, "_get_digests", None)
            if f is None:
                continue
            mdigests = manifest.distfiles
            old_digests = []
            for pkg in pkgset:
                try:
                    digests = f(pkg, force_manifest1=True)
                    self.check_pkg(pkg, mdigests, digests, reporter)
                    old_digests += digests.keys()
                except MissingChksum, e:
                    reporter.add_report(MissingDigest(pkg,e))
            orphaned = set(mdigests).difference(old_digests)
            if orphaned:
                reporter.add_report(OrphanedManifestDist(pkgset[0], orphaned))

    def check_pkg(self, pkg, mdigests, digests, reporter):

        for fname, chksum in digests.iteritems():
            mchksum = mdigests.get(fname, None)
            if mchksum is None:
                reporter.add_report(ManifestDigestConflict(pkg, fname,
                    "missing in manifest"))
                continue
            conflicts = []
            for chf in set(chksum).intersection(mchksum):
                if mchksum[chf] != chksum[chf]:
                    conflicts.append((chf, mchksum[chf], chksum[chf]))
            if conflicts:
                reporter.add_report(ManifestDigestConflict(pkg, fname,
                    "chksum conflict- %r" % 
                        tuple(sorted(reformat_chksums(conflicts)))
                ))
