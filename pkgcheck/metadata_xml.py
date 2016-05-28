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
    'functools:partial',
    'lxml:etree',
    'tempfile:NamedTemporaryFile',
    'pkgcore.ebuild.atom:atom',
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
        return "%s is missing %s" % (
            self._label, os.path.basename(self.filename))


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
        return "%s %s is not well formed xml" % (
            self._label, os.path.basename(self.filename))


class base_InvalidXml(base.Error):
    """xml fails XML Schema validation"""

    __slots__ = ("category", "package", "filename")
    __attrs__ = __slots__

    # message first so partial() can be easily applied
    def __init__(self, message, filename, category, package=None):
        super(base_InvalidXml, self).__init__()
        self.message = message
        self.category = category
        self.package = package
        self.filename = filename

    @property
    def _label(self):
        if self.package is not None:
            return "%s/%s" % (self.category, self.package)
        return self.category

    @staticmethod
    def format_lxml_errors(error_log):
        for l in error_log:
            yield 'line %d, col %d: (%s) %s' % (
                l.line, l.column, l.type_name, l.message)

    @property
    def short_desc(self):
        return "%s %s violates metadata.xsd:\n%s" % (
            self._label, os.path.basename(self.filename),
            '\n'.join(self.format_lxml_errors(self.message)))


class base_MetadataXmlInvalidPkgRef(base.Error):
    """ metadata.xml <pkg/> references unavailable / invalid package """

    __slots__ = ("category", "package", "filename")
    __attrs__ = __slots__

    def __init__(self, pkgtext, filename, category, package=None):
        super(base_MetadataXmlInvalidPkgRef, self).__init__()
        self.category = category
        self.package = package
        self.filename = filename
        self.pkgtext = pkgtext

    @property
    def _label(self):
        if self.package is not None:
            return "%s/%s" % (self.category, self.package)
        return self.category

    @property
    def short_desc(self):
        return "%s %s <pkg/> references unknown/invalid package: %r" % (
            self._label, os.path.basename(self.filename), self.pkgtext)


class base_MetadataXmlInvalidCatRef(base.Error):
    """ metadata.xml <cat/> references unavailable / invalid category """

    __slots__ = ("category", "package", "filename")
    __attrs__ = __slots__

    def __init__(self, cattext, filename, category, package=None):
        super(base_MetadataXmlInvalidPkgRef, self).__init__()
        self.category = category
        self.package = package
        self.filename = filename
        self.cattext = cattext

    @property
    def _label(self):
        if self.package is not None:
            return "%s/%s" % (self.category, self.package)
        return self.category

    @property
    def short_desc(self):
        return "%s %s <cat/> references unknown/invalid category: %r" % (
            self._label, os.path.basename(self.filename), self.cattext)


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


class PkgMetadataXmlInvalidPkgRef(base_MetadataXmlInvalidPkgRef):
    __slots__ = ()
    threshold = base.package_feed


class CatMetadataXmlInvalidPkgRef(base_MetadataXmlInvalidPkgRef):
    __slots__ = ()
    threshold = base.category_feed


class PkgMetadataXmlInvalidCatRef(base_MetadataXmlInvalidCatRef):
    __slots__ = ()
    threshold = base.package_feed


class CatMetadataXmlInvalidCatRef(base_MetadataXmlInvalidCatRef):
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
        self.pkgref_cache = {}

    def feed(self, thing, reporter):
        raise NotImplementedError(self.feed)

    def finish(self, reporter):
        self.last_seen = None

    def check_doc(self, doc):
        """ Perform additional document structure checks """
        for el in doc.findall('.//cat'):
            c = el.text.strip()
            if c not in self.options.search_repo.categories:
                yield partial(self.catref_error, c)

        for el in doc.findall('.//pkg'):
            p = el.text.strip()
            if p not in self.pkgref_cache:
                try:
                    a = atom(p)
                    found = self.options.search_repo.has_match(a)
                except Exception:
                    # invalid atom
                    found = False
                self.pkgref_cache[p] = found

            if not self.pkgref_cache[p]:
                yield partial(self.pkgref_error, p)

    def check_file(self, loc):
        try:
            doc = etree.parse(loc)
        except (IOError, OSError):
            return (None, (self.missing_error,))
        except etree.XMLSyntaxError:
            return (None, (self.misformed_error,))

        # note: while doc is available, do not pass it here as it may
        # trigger undefined behavior due to incorrect structure
        if not self.schema.validate(doc):
            return (None, (partial(self.invalid_error, self.schema.error_log),))

        return (doc, self.check_doc(doc))


class PackageMetadataXmlCheck(base_check):
    """package level metadata.xml scans"""

    feed_type = base.versioned_feed
    scope = base.package_scope
    misformed_error = PkgBadlyFormedXml
    invalid_error = PkgInvalidXml
    missing_error = PkgMissingMetadataXml
    catref_error = PkgMetadataXmlInvalidCatRef
    pkgref_error = PkgMetadataXmlInvalidPkgRef

    known_results = (
        PkgBadlyFormedXml, PkgInvalidXml, PkgMissingMetadataXml,
        PkgMetadataXmlInvalidPkgRef, PkgMetadataXmlInvalidCatRef)

    def feed(self, pkg, reporter):
        if self.last_seen == pkg.key:
            return
        self.last_seen = pkg.key
        loc = pjoin(os.path.dirname(pkg.ebuild.path), "metadata.xml")
        doc, reports = self.check_file(loc)
        for ret in reports:
            reporter.add_report(ret(loc, pkg.category, pkg.package))


class CategoryMetadataXmlCheck(base_check):
    """metadata.xml scans"""
    feed_type = base.versioned_feed
    scope = base.category_scope
    misformed_error = CatBadlyFormedXml
    invalid_error = CatInvalidXml
    missing_error = CatMissingMetadataXml
    catref_error = CatMetadataXmlInvalidCatRef
    pkgref_error = CatMetadataXmlInvalidPkgRef

    known_results = (
        CatBadlyFormedXml, CatInvalidXml, CatMissingMetadataXml,
        CatMetadataXmlInvalidPkgRef, CatMetadataXmlInvalidCatRef)

    def feed(self, pkg, reporter):
        if self.last_seen == pkg.category:
            return
        self.last_seen = pkg.category
        loc = os.path.join(self.repo_base, pkg.category, "metadata.xml")
        doc, reports = self.check_file(loc)
        for ret in reports:
            reporter.add_report(ret(loc, pkg.category))


def noop_validator(loc):
    return 0
