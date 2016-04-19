# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: BSD/GPL2

import os

from snakeoil import compatibility
from snakeoil.demandload import demandload

from pkgcheck import base

if compatibility.is_py3k:
    urllib_path = 'urllib.request:urlopen'
    demandload(
        'urllib.request:urlopen',
        'urllib:error@urllib_error')
else:
    # yes, this is a bit special.  We do this
    # since the two parts we want, exist
    # in different modules dependant on py2k/py3k.
    demandload(
        'urllib2@urllib_error',
        'urllib2:urlopen')
demandload(
    'argparse',
    'lxml:etree',
    'tempfile:NamedTemporaryFile',
    'pkgcore.log:logger',
    'pkgcore.spawn:spawn,find_binary',
    'snakeoil.osutils:pjoin',
    'snakeoil:fileutils',
)


class base_MissingXml(base.Error):
    """required xml file is missing"""

    __slots__ = ('category', 'package', 'filename')
    __attrs__ = __slots__

    def __init__(self, filename, category, package=None):
        super(base_MissingXml, self).__init__()
        self.category = category
        self.package = package
        self.filename = filename

    @property
    def _label(self):
        if self.package is not None:
            return "%s/%s" % (self.category, self.package)
        return self.category

    @property
    def short_desc(self):
        return "%s is missing %s" % (self._label, os.path.basename(self.filename))


class base_BadlyFormedXml(base.Warning):
    """xml isn't well formed"""

    __slots__ = ("category", "package", "filename")
    __attrs__ = __slots__

    def __init__(self, filename, category, package=None):
        super(base_BadlyFormedXml, self).__init__()
        self.category = category
        self.package = package
        self.filename = filename

    @property
    def _label(self):
        if self.package is not None:
            return "%s/%s" % (self.category, self.package)
        return self.category

    @property
    def short_desc(self):
        return "%s %s is not well formed xml" % (self._label, os.path.basename(self.filename))


class base_InvalidXml(base.Error):
    """xml fails XML Schema validation"""

    __slots__ = ("category", "package", "filename")
    __attrs__ = __slots__

    def __init__(self, filename, category, package=None):
        super(base_InvalidXml, self).__init__()
        self.category = category
        self.package = package
        self.filename = filename

    @property
    def _label(self):
        if self.package is not None:
            return "%s/%s" % (self.category, self.package)
        return self.category

    @property
    def short_desc(self):
        return "%s %s violates metadata.xsd" % (self._label, os.path.basename(self.filename))


class PkgMissingMetadataXml(base_MissingXml):
    __slots__ = ()
    threshold = base.package_feed


class CatMissingMetadataXml(base_MissingXml):
    __slots__ = ()
    threshold = base.category_feed


class PkgInvalidXml(base_InvalidXml):
    __slots__ = ()
    threshold = base.package_feed


class CatInvalidXml(base_InvalidXml):
    __slots__ = ()
    threshold = base.category_feed


class PkgBadlyFormedXml(base_BadlyFormedXml):
    __slots__ = ()
    threshold = base.package_feed


class CatBadlyFormedXml(base_BadlyFormedXml):
    __slots__ = ()
    threshold = base.category_feed


class base_check(base.Template):
    """base class for metadata.xml scans"""

    xsd_url = "http://www.gentoo.org/xml-schema/metadata.xsd"
    misformed_error = None
    invalid_error = None
    missing_error = None

    @classmethod
    def mangle_argparser(cls, parser):
        try:
            parser.plugin.add_argument(
                '--metadata-xsd',
                help='location to cache %s' % (cls.xsd_url,))
            parser.plugin.add_argument(
                '--metadata-xsd-required',
                help="if metadata.xsd cannot be fetched (no connection for example), "
                     "treat it as a failure rather than warning and ignoring.")
        except argparse.ArgumentError:
            # the arguments have already been added to the parser
            pass

    def __init__(self, options):
        base.Template.__init__(self, options)
        self.repo_base = getattr(options.src_repo, "location", None)
        self.xsd_file = None

    def start(self):
        self.last_seen = None
        refetch = False
        write_path = read_path = self.options.metadata_xsd
        if write_path is None:
            read_path = pjoin(self.repo_base, 'metadata', 'xml-schema', 'metadata.xsd')
        refetch = not os.path.isfile(read_path)

        if refetch:
            logger.warn('metadata.xsd cannot be opened from %s, will refetch', read_path)
            logger.info("fetching metdata.xsd from %s", self.xsd_url)
            try:
                xsd_data = urlopen(self.xsd_url).read()
            except urllib_error.URLError as e:
                if self.options.metadata_xsd_required:
                    raise Exception(
                        "failed fetching xsd from %s: reason %s. "
                        "Due to --metadata-xsd-required in use, bailing" %
                        (self.xsd_url, e.reason))
                logger.warn(
                    "failed fetching XML Schema from %s: reason %s", self.xsd_url, e.reason)
                self.validator = noop_validator
                return
            if write_path is None:
                self.xsd_file = NamedTemporaryFile()
                write_path = read_path = self.xsd_file.name
            try:
                fileutils.write_file(write_path, 'wb', xsd_data)
            except EnvironmentError as e:
                if self.options.metadata_xsd_required:
                    raise Exception(
                        "failed saving XML Schema to %s: reason %s. "
                        "Due to --metadata-xsd-required in use, bailing" %
                        (write_path, e))
                logger.warn("failed writing XML Schema to %s: reason %s.  Disabling check." %
                            (write_path, e))
                self.validator = noop_validator
                return

        self.schema = etree.XMLSchema(etree.parse(read_path))

    def feed(self, thing, reporter):
        raise NotImplementedError(self.feed)

    def finish(self, reporter):
        self.last_seen = None

    def check_file(self, loc):
        try:
            doc = etree.parse(loc)
        except (IOError, OSError):
            return self.missing_error
        except etree.XMLSyntaxError:
            return self.misformed_error

        if not self.schema.validate(doc):
            return self.invalid_error

        return 0


class PackageMetadataXmlCheck(base_check):
    """package level metadata.xml scans"""

    feed_type = base.versioned_feed
    scope = base.package_scope
    misformed_error = PkgBadlyFormedXml
    invalid_error = PkgInvalidXml
    missing_error = PkgMissingMetadataXml

    known_results = (PkgBadlyFormedXml, PkgInvalidXml, PkgMissingMetadataXml)

    def feed(self, pkg, reporter):
        if self.last_seen == pkg.key:
            return
        self.last_seen = pkg.key
        loc = pjoin(os.path.dirname(pkg.ebuild.path), "metadata.xml")
        ret = self.check_file(loc)
        if ret is not None:
            reporter.add_report(ret(loc, pkg.category, pkg.package))


class CategoryMetadataXmlCheck(base_check):
    """metadata.xml scans"""
    feed_type = base.versioned_feed
    scope = base.category_scope
    misformed_error = CatBadlyFormedXml
    invalid_error = CatInvalidXml
    missing_error = CatMissingMetadataXml

    known_results = (CatBadlyFormedXml, CatInvalidXml, CatMissingMetadataXml)

    def feed(self, pkg, reporter):
        if self.last_seen == pkg.category:
            return
        self.last_seen = pkg.category
        loc = os.path.join(self.repo_base, pkg.category, "metadata.xml")
        ret = self.check_file(loc)
        if ret is not None:
            reporter.add_report(ret(loc, pkg.category))


def noop_validator(loc):
        return 0
