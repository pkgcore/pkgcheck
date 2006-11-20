# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: GPL2

from pkgcore_checks import base, util, addons
from pkgcore.util.demandload import demandload
import operator, itertools

demandload(globals(), "pkgcore.util.xml:escape "
    "pkgcore.util.osutils:listdir_files "
    "pkgcore.util.lists:iflatten_instance "
    "pkgcore.fetch:fetchable ")

class UnusedLocalFlags(base.Template):

    """
    check for unused use.local.desc entries
    """

    feed_type = base.package_feed
    required_addons = (addons.ProfileAddon,)

    def __init__(self, options, profiles):
        base.Template.__init__(self, options)
        self.flags = {}

    def feed(self, pkgsets, reporter):
        self.flags = util.get_use_local_desc(self.options.profile_base_dir)
        for pkgs in pkgsets:
            yield pkgs
            for restrict, flags in self.flags.get(pkgs[0].key, {}).iteritems():
                unused = flags.difference(iflatten_instance(
                    pkg.iuse for pkg in pkgs if restrict.match(pkg)))
                if unused:
                    reporter.add_report(UnusedLocalFlagsResult(restrict,
                                                               unused))


class UnusedLocalFlagsResult(base.Result):
    
    """
    unused use.local.desc flag(s)
    """
    
    __slots__ = ("category", "package", "atom", "flags")

    def __init__(self, restrict, flags):
        base.Result.__init__(self)
        # tricky, but it works; atoms have the same attrs
        self._store_cp(restrict)
        self.atom = str(restrict)
        self.flags = tuple(sorted(flags))
    
    def to_str(self):
        if self.atom == "%s/%s" % (self.category, self.package):
            s = ''
        else:
            s = "atom(%s), " % self.atom
        return "%s/%s: use.local.desc%s unused flag(s): %s" % \
            (self.category, self.package, s,
		', '.join(self.flags))

    def to_xml(self):
        return \
"""<check name="%s">
    <category>%s</category>
    <package>%s</package>
    <msg>%s</msg>
</check>""" % (self.__class__.__name__, self.category, self.package,
    escape("atom %s unused use.local.desc flags: %s" % 
	(self.atom, ', '.join(self.flags))))


class UnusedGlobalFlags(base.Template):
    """
    check for unused use.desc entries
    """

    feed_type = base.versioned_feed
    scope = base.repository_scope
    required_addons = (addons.ProfileAddon,)

    def __init__(self, options, profiles):
        base.Template.__init__(self, options)
        self.flags = None

    def feed(self, pkgs, reporter):
        self.flags = set(util.get_use_desc(self.options.profile_base_dir))
        for pkg in pkgs:
            yield pkg
            self.flags.difference_update(pkg.iuse)
        if self.flags:
            reporter.add_report(UnusedGlobalFlagsResult(self.flags))
        self.flags.clear()


class UnusedGlobalFlagsResult(base.Result):
    
    """
    unused use.desc flag(s)
    """
    
    __slots__ = ("flags",)

    def __init__(self, flags):
        base.Result.__init__(self)
        # tricky, but it works; atoms have the same attrs
        self.flags = tuple(sorted(flags))
    
    def to_str(self):
        return "use.desc unused flag(s): %s" % \
    		', '.join(self.flags)

    def to_xml(self):
        return \
"""<check name="%s">
    <msg>%s</msg>
</check>""" % (self.__class__.__name__, 
    escape("use.desc unused flags: %s" % ', '.join(self.flags)))


class UnusedLicense(base.Template):
    """
    unused license file(s) check
    """

    feed_type = base.versioned_feed
    scope = base.repository_scope
    required_addons = (addons.LicenseAddon,)

    def __init__(self, options, licenses):
        base.Template.__init__(self, options)
        self.licenses = None

    def feed(self, pkgs, reporter):
        self.licenses = set()
        for license_dirs in self.options.license_dirs:
            self.licenses.update(listdir_files(license_dir))
        for pkg in pkgs:
            yield pkg
            self.licenses.difference_update(iflatten_instance(pkg.license))
        if self.licenses:
            reporter.add_report(UnusedLicenseReport(self.licenses))
        self.licenses = None


class UnusedLicenseReport(base.Result):
    """
    unused license(s) detected
    """
    
    __slots__ = ("licenses",)
    
    def __init__(self, licenses):
        base.Result.__init__(self)
        self.licenses = tuple(sorted(licenses))
    
    def to_str(self):
        return "unused license(s): %s" % \
            ', '.join(self.licenses)
            
    def to_xml(self):
        return \
"""<check name="%s">
    <msg>%s</msg>
</check>""" % (self.__class__.__name__, 
    escape("use.desc unused licenses: %s" % ', '.join(self.licenses)))


class ConflictingDigests(base.Template):
    """
    scan for conflicting digest entries; since this requires
    keeping all fetchables in memory, this can add up.
    """

    scope = base.package_scope
    feed_type = base.versioned_feed

    def __init__(self, options):
        base.Template.__init__(self, options)
        self._fetchables = {}

    def feed(self, pkgs, reporter):
        for pkg in pkgs:
            yield pkg
            self._feed(pkg, reporter)
        self._fetchables.clear()

    def _feed(self, pkg, reporter):
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


def reformat_chksums(iterable):
    for chf, val1, val2 in iterable:
        if chf == "size":
            yield chf, val1, val2
        else:
            yield chf, "%x" % val1, "%x" % val2
    


class ConflictingChksums(base.Result):

    __slots__ = ("category", "package", "version", "owning_pkgs",
        "filename", "chksums")
    
    _sorter = staticmethod(operator.itemgetter(0))
    
    def __init__(self, pkg, filename, chksums, others):
        base.Result.__init__(self)
        self._store_cpv(pkg)
        self.filename = filename
        self.chksums = tuple(sorted(reformat_chksums(chksums),
            key=self._sorter))
        self.others = tuple(sorted(others))

    def to_str(self):
        return "%s/%s-%s: conflicts with (%s) for file %r, chksums: %s" % \
            (self.category, self.package, self.version, \
            ', '.join(self.others), self.filename, self.chksums)

    def to_xml(self):
        return \
"""<check name="%s">
    <category>%s</category>
    <package>%s</package>
    <version>%s</version>
    <msg>%s</msg>
</check>""" % (self.__class__.__name__,  self.category, self.package, 
    self.version,
    escape("file %r conflicts with %r, chksums: %r" % \
        self.filename, self.others, self.chksums))


class ConflictManifestDigest(base.Template):

    """Scan for conflicts between the Manifest file and digest files."""

    feed_type = base.package_feed
    
    repo_grabber = operator.attrgetter("repo")

    def feed(self, pkgsets, reporter):
        for pkgset in pkgsets:
            yield pkgset
            self._feed(pkgset, reporter)

    def _feed(self, full_pkgset, reporter):
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
                digests = f(pkg, force_manifest1=True)
                self.check_pkg(pkg, mdigests, digests, reporter)
                old_digests += digests.keys()
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

class ManifestDigestConflict(base.Result):
    __slots__ = ("category", "package", "version", 
        "msg", "filename")

    def __init__(self, pkg, filename, msg):
        base.Result.__init__(self)
        self._store_cpv(pkg)
        self.filename = filename
        self.msg = msg
    
    def to_str(self):
        return "%s/%s-%s: file %r: %s" % (self.category, self.package,
            self.version, self.filename, self.msg)
    
    def to_xml(self):
        return \
"""<check name="%s">
    <category>%s</category>
    <package>%s</package>
    <version>%s</version>
    <msg>%s</msg>
</check>""" % (self.__class__.__name__,  self.category, self.package, 
    self.version,
    escape("file %s: %s" % (self.filename, self.msg)))


class OrphanedManifestDist(base.Result):
    __slots__ = ("category", "package", "version",
        "files")

    def __init__(self, pkg, files):
        base.Result.__init__(self)
        self._store_cp(pkg)
        self.files = tuple(sorted(files))
    
    def to_str(self):
        return "%s/%s: manifest2 knows of dists %r, but digest1 doesn't" % \
            (self.category, self.package, self.files)

    def to_xml(self):
        return \
"""<check name="%s">
    <category>%s</category>
    <package>%s</package>
    <msg>%s</msg>
</check>""" % (self.__class__.__name__,  self.category, self.package, 
    escape("manifest2 knows of %r, but they're not in digests" % self.files))
