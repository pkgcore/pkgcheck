# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: BSD/GPL2

from itertools import ifilter
from operator import attrgetter

from pkgcore.ebuild.atom import MalformedAtom, atom
from pkgcore.fetch import fetchable
from pkgcore.package.errors import MetadataException
from snakeoil.demandload import demandload

from pkgcheck import base, addons

demandload('logging')


class MetadataError(base.Result):
    """problem detected with a packages metadata"""
    __slots__ = ("category", "package", "version", "attr", "msg")
    threshold = base.versioned_feed

    def __init__(self, pkg, attr, msg):
        base.Result.__init__(self)
        self._store_cpv(pkg)
        self.attr, self.msg = attr, str(msg)

    @property
    def short_desc(self):
        return "attr(%s): %s" % (self.attr, self.msg)


class MissingLicense(base.Result):
    """used license(s) have no matching license file(s)"""

    __slots__ = ("category", "package", "version", "licenses")
    threshold = base.versioned_feed

    def __init__(self, pkg, licenses):
        self._store_cpv(pkg)
        self.licenses = tuple(sorted(licenses))

    @property
    def short_desc(self):
        return "no license files: %s" % ', '.join(self.licenses)


class LicenseMetadataReport(base.Template):

    """LICENSE metadata key validity checks"""

    known_results = (MetadataError, MissingLicense) + \
        addons.UseAddon.known_results
    feed_type = base.versioned_feed

    required_addons = (
        addons.UseAddon, addons.ProfileAddon, addons.LicenseAddon)

    def __init__(self, options, iuse_handler, profiles, licenses):
        base.Template.__init__(self, options)
        self.iuse_filter = iuse_handler.get_filter('license')
        self.license_handler = licenses

    def start(self):
        self.licenses = self.license_handler.licenses

    def finish(self, reporter):
        self.licenses = None

    def feed(self, pkg, reporter):
        try:
            licenses = pkg.license
        except (KeyboardInterrupt, SystemExit):
            raise
        except (MetadataException, MalformedAtom, ValueError), e:
            reporter.add_report(MetadataError(
                pkg, 'license', "error- %s" % e))
            del e
        except Exception, e:
            logging.exception(
                "unknown exception caught for pkg(%s) attr(%s): "
                "type(%s), %s" % (pkg, 'license', type(e), e))
            reporter.add_report(MetadataError(
                pkg, 'license', "exception- %s" % e))
            del e
        else:
            i = self.iuse_filter((basestring,), pkg, licenses, reporter)
            if self.licenses is None:
                # force a walk of it so it'll report if needs be.
                for x in i:
                    pass
            else:
                licenses = set(i)
                if not licenses:
                    if pkg.category != 'virtual':
                        reporter.add_report(MetadataError(
                            pkg, "license", "no license defined"))
                else:
                    licenses.difference_update(self.licenses)
                    if licenses:
                        reporter.add_report(MissingLicense(pkg, licenses))


class IUSEMetadataReport(base.Template):

    """Check IUSE for valid use flags"""

    required_addons = (addons.UseAddon,)
    known_results = (MetadataError,) + addons.UseAddon.known_results

    feed_type = base.versioned_feed

    def __init__(self, options, iuse_handler):
        base.Template.__init__(self, options)
        self.iuse_handler = iuse_handler

    def feed(self, pkg, reporter):
        if not self.iuse_handler.ignore:
            iuse = pkg.iuse_stripped.difference(self.iuse_handler.allowed_iuse(pkg))
            if iuse:
                reporter.add_report(MetadataError(
                    pkg, "iuse", "iuse unknown flag%s: [ %s ]" % (
                        's'[len(iuse) == 1:], ", ".join(iuse))))


class UnusedLocalFlags(base.Result):

    """
    unused local use flag(s)
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
        return "metadata.xml unused local use flag%s: [ %s ]" % (
            's'[len(self.flags) == 1:], ', '.join(self.flags))


class UnusedLocalFlagsReport(base.Template):

    """
    check for unused local use flags in metadata.xml
    """

    feed_type = base.package_feed
    required_addons = (addons.UseAddon,)
    known_results = (UnusedLocalFlags,) + addons.UseAddon.known_results

    def __init__(self, options, use_handler):
        base.Template.__init__(self, options)
        self.iuse_handler = use_handler

    def feed(self, pkgs, reporter):
        unused = set()
        for pkg in pkgs:
            unused.update(pkg.local_use)
        for pkg in pkgs:
            unused.difference_update(pkg.iuse_stripped)
        if unused:
            reporter.add_report(UnusedLocalFlags(pkg, unused))


class DependencyReport(base.Template):

    """check DEPEND, RDEPEND, and PDEPEND"""

    required_addons = (addons.UseAddon,)
    known_results = (MetadataError,) + addons.UseAddon.known_results
    blocks_getter = attrgetter('blocks')

    feed_type = base.versioned_feed

    attrs = tuple((x, attrgetter(x)) for x in
                  ("depends", "rdepends", "post_rdepends"))

    def __init__(self, options, iuse_handler):
        base.Template.__init__(self, options)
        self.iuse_filter = iuse_handler.get_filter()

    def feed(self, pkg, reporter):
        for attr_name, getter in self.attrs:
            try:
                i = self.iuse_filter(
                    (atom,), pkg, getter(pkg), reporter, attr=attr_name)
                for x in ifilter(self.blocks_getter, i):
                    if x.match(pkg):
                        reporter.add_report(MetadataError(pkg, attr_name, "blocks itself"))
            except (KeyboardInterrupt, SystemExit):
                raise
            except (MetadataException, MalformedAtom, ValueError), e:
                reporter.add_report(MetadataError(
                    pkg, attr_name, "error- %s" % e))
                del e
            except Exception, e:
                logging.exception(
                    "unknown exception caught for pkg(%s) attr(%s): "
                    "type(%s), %s" % (pkg, attr_name, type(e), e))
                reporter.add_report(MetadataError(
                    pkg, attr_name, "exception- %s" % e))
                del e


class StupidKeywords(base.Result):
    """pkg that is using -*; package.mask in profiles addresses this already"""

    __slots__ = ('category', 'package', 'version')
    threshold = base.versioned_feed

    def __init__(self, pkg):
        base.Result.__init__(self)
        self._store_cpv(pkg)

    short_desc = (
        "keywords contain -*; use package.mask or empty keywords instead")


class KeywordsReport(base.Template):

    """
    check pkgs keywords for sanity; empty keywords, and -* are flagged
    """

    feed_type = base.versioned_feed
    known_results = (StupidKeywords, MetadataError)

    def feed(self, pkg, reporter):
        if "-*" in pkg.keywords and len(pkg.keywords) == 1:
            reporter.add_report(StupidKeywords(pkg))


class MissingUri(base.Result):
    """restrict=fetch isn't set, yet no full uri exists"""
    __slots__ = ("category", "package", "version", "filename")
    threshold = base.versioned_feed

    def __init__(self, pkg, filename):
        base.Result.__init__(self)
        self._store_cpv(pkg)
        self.filename = filename

    @property
    def short_desc(self):
        return "file %s is unfetchable- no URI available, and RESTRICT=fetch " \
            "isn't set" % self.filename


class BadProto(base.Result):
    """bad protocol"""
    __slots__ = ("category", "package", "version", "filename", "bad_uri")
    threshold = base.versioned_feed

    def __init__(self, pkg, filename, bad_uri):
        base.Result.__init__(self)
        self._store_cpv(pkg)
        self.filename = filename
        self.bad_uri = tuple(sorted(bad_uri))

    @property
    def short_desc(self):
        return "file %s: bad protocol/uri: %r " % (self.filename, self.bad_uri)


class SrcUriReport(base.Template):

    """SRC_URI related checks.

    verify that it's a valid/fetchable uri, port 80,443,23
    """

    required_addons = (addons.UseAddon,)
    feed_type = base.versioned_feed
    known_results = (BadProto, MissingUri, MetadataError) + \
        addons.UseAddon.known_results

    valid_protos = frozenset(["http", "https", "ftp"])

    def __init__(self, options, iuse_handler):
        base.Template.__init__(self, options)
        self.iuse_filter = iuse_handler.get_filter('fetchables')

    def feed(self, pkg, reporter):
        try:
            lacks_uri = set()
            # duplicate entries are possible.
            seen = set()
            for f_inst in self.iuse_filter((fetchable,), pkg,
                                           pkg.fetchables, reporter):
                if f_inst.filename in seen:
                    continue
                seen.add(f_inst.filename)
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

        except (KeyboardInterrupt, SystemExit):
            raise
        except (MetadataException, MalformedAtom, ValueError), e:
            reporter.add_report(MetadataError(
                pkg, 'fetchables', "error- %s" % e))
            del e
        except Exception, e:
            logging.exception(
                "unknown exception caught for pkg(%s): "
                "type(%s), %s" % (pkg, type(e), e))
            reporter.add_report(MetadataError(
                pkg, 'fetchables',
                "exception- %s" % e))
            del e


class CrappyDescription(base.Result):

    """pkg's description sucks in some fashion"""

    __slots__ = ("category", "package", "version", "msg")
    threshold = base.versioned_feed

    def __init__(self, pkg, msg):
        base.Result.__init__(self)
        self._store_cpv(pkg)
        self.msg = msg

    @property
    def short_desc(self):
        return "description needs improvement: %s" % self.msg


class DescriptionReport(base.Template):
    """
    DESCRIPTION checks.
    check on length (<=250), too short (<5), or generic (lifted from eclass or
    just using the pkgs name
    """

    feed_type = base.versioned_feed
    known_results = (CrappyDescription,)

    def feed(self, pkg, reporter):
        s = pkg.description.lower()

        if s.startswith("based on") and "eclass" in s:
            reporter.add_report(CrappyDescription(
                pkg, "generic eclass defined description"))

        elif pkg.package == s or pkg.key == s:
            reporter.add_report(CrappyDescription(
                pkg, "using the pkg name as the description isn't very helpful"))

        else:
            l = len(pkg.description)
            if not l:
                reporter.add_report(CrappyDescription(
                    pkg, "empty/unset"))
            elif l > 250:
                reporter.add_report(CrappyDescription(
                    pkg, "over 250 chars in length, bit long"))
            elif l < 5:
                reporter.add_report(CrappyDescription(
                    pkg, "under 10 chars in length- too short"))


class BadRestricts(base.Result):
    """pkg's restrict metadata has unknown/deprecated entries"""

    __slots__ = ("category", "package", "version", "restricts", "deprecated")
    threshold = base.versioned_feed

    def __init__(self, pkg, restricts, deprecated=None):
        base.Result.__init__(self)
        self._store_cpv(pkg)
        self.restricts = restricts
        self.deprecated = deprecated
        if not restricts and not deprecated:
            raise TypeError("deprecated or restricts must not be empty")

    @property
    def short_desc(self):
        s = ''
        if self.restricts:
            s = "unknown restricts: %s" % ", ".join(self.restricts)
        if self.deprecated:
            if s:
                s += "; "
            s += "deprecated (drop the 'no') [ %s ]" % ", ".join(
                self.deprecated)
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
        "restricts:%s" % ", ".join(sorted(known_restricts))

    def __init__(self, options, iuse_handler):
        base.Template.__init__(self, options)
        self.iuse_filter = iuse_handler.get_filter('restrict')

    def feed(self, pkg, reporter):
        # ignore conditionals
        i = self.iuse_filter((basestring,), pkg, pkg.restrict, reporter)
        bad = set(i).difference(self.known_restricts)
        if bad:
            deprecated = set(x for x in bad if x.startswith("no")
                             and x[2:] in self.known_restricts)
            reporter.add_report(BadRestricts(
                pkg, bad.difference(deprecated), deprecated))
