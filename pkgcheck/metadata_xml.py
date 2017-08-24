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
    'itertools:chain',
    'lxml:etree',
    'tempfile:NamedTemporaryFile',
    'pkgcore.ebuild.atom:atom',
    'pkgcore.log:logger',
    'snakeoil.osutils:pjoin',
    'snakeoil:fileutils',
    'snakeoil.strings:pluralism',
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
    """Package is missing metadata.xml."""
    __slots__ = ()
    threshold = base.package_feed


class CatMissingMetadataXml(base_MissingXml):
    """Category is missing metadata.xml."""
    __slots__ = ()
    threshold = base.category_feed


class PkgInvalidXml(base_InvalidXml):
    """Invalid package metadata.xml."""
    __slots__ = ()
    threshold = base.package_feed


class CatInvalidXml(base_InvalidXml):
    """Invalid category metadata.xml."""
    __slots__ = ()
    threshold = base.category_feed


class PkgBadlyFormedXml(base_BadlyFormedXml):
    """Badly formed package metadata.xml."""
    __slots__ = ()
    threshold = base.package_feed


class CatBadlyFormedXml(base_BadlyFormedXml):
    """Badly formed category metadata.xml."""
    __slots__ = ()
    threshold = base.category_feed


class PkgMetadataXmlInvalidPkgRef(base_MetadataXmlInvalidPkgRef):
    """Invalid package reference in package metadata.xml."""
    __slots__ = ()
    threshold = base.package_feed


class CatMetadataXmlInvalidPkgRef(base_MetadataXmlInvalidPkgRef):
    """Invalid package reference in category metadata.xml."""
    __slots__ = ()
    threshold = base.category_feed


class PkgMetadataXmlInvalidCatRef(base_MetadataXmlInvalidCatRef):
    """Invalid category reference in package metadata.xml."""
    __slots__ = ()
    threshold = base.package_feed


class CatMetadataXmlInvalidCatRef(base_MetadataXmlInvalidCatRef):
    """Invalid category reference in category metadata.xml."""
    __slots__ = ()
    threshold = base.category_feed


class MetadataXmlIndentation(base.Warning):
    """Inconsistent indentation in metadata.xml file."""

    __slots__ = ("category", "package", "version", "lines")

    def __init__(self, lines, filename, category, package=None):
        super(MetadataXmlIndentation, self).__init__()
        self.lines = lines
        self.filename = filename
        self.category = category
        self.package = package

    @property
    def short_desc(self):
        return "metadata.xml has inconsistent indentation"

    @property
    def long_desc(self):
        return "%s on line%s %s" % (
            self.short_desc, pluralism(self.lines), ', '.join(str(x) for x in self.lines))


class CatMetadataXmlIndentation(MetadataXmlIndentation):
    """Inconsistent indentation in category metadata.xml file."""
    __slots__ = ()
    threshold = base.category_feed

class PkgMetadataXmlIndentation(MetadataXmlIndentation):
    """Inconsistent indentation in package metadata.xml file."""
    __slots__ = ()
    threshold = base.package_feed


class base_check(base.Template):
    """base class for metadata.xml scans"""

    xsd_url = "http://www.gentoo.org/xml-schema/metadata.xsd"
    schema = None

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
        super(base_check, self).__init__(options)
        self.repo_base = options.target_repo.location
        self.xsd_file = None

    def start(self):
        if base_check.schema is None:
            refetch = False
            write_path = read_path = self.options.metadata_xsd
            if write_path is None:
                read_path = pjoin(self.repo_base, 'metadata', 'xml-schema', 'metadata.xsd')
            refetch = not os.path.isfile(read_path)

            if refetch:
                if self.options.verbose:
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

            base_check.schema = etree.XMLSchema(etree.parse(read_path))

        self.pkgref_cache = {}

    def feed(self, thing, reporter):
        raise NotImplementedError(self.feed)

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

    def check_whitespace(self, loc):
        orig_indent = None
        indents = set()
        with open(loc) as f:
            for lineno, line in enumerate(f):
                for i in line[:-len(line.lstrip())]:
                    if i != orig_indent:
                        if orig_indent is None:
                            orig_indent = i
                        else:
                            indents.update([lineno + 1])
        if indents:
            yield partial(self.indent_error, indents)

    def check_file(self, loc):
        try:
            doc = etree.parse(loc)
        except (IOError, OSError):
            return self.missing_error
        except etree.XMLSyntaxError:
            return self.misformed_error

        # note: while doc is available, do not pass it here as it may
        # trigger undefined behavior due to incorrect structure
        if not self.schema.validate(doc):
            return partial(self.invalid_error, self.schema.error_log)

        return chain.from_iterable((self.check_doc(doc), self.check_whitespace(loc)))


class PackageMetadataXmlCheck(base_check):
    """package level metadata.xml scans"""

    feed_type = base.package_feed
    scope = base.package_scope
    misformed_error = PkgBadlyFormedXml
    invalid_error = PkgInvalidXml
    missing_error = PkgMissingMetadataXml
    catref_error = PkgMetadataXmlInvalidCatRef
    pkgref_error = PkgMetadataXmlInvalidPkgRef
    indent_error = PkgMetadataXmlIndentation

    known_results = (
        PkgBadlyFormedXml, PkgInvalidXml, PkgMissingMetadataXml,
        PkgMetadataXmlInvalidPkgRef, PkgMetadataXmlInvalidCatRef,
        PkgMetadataXmlIndentation)

    def feed(self, pkgs, reporter):
        # package with no ebuilds, skipping check
        if not pkgs:
            return
        pkg = pkgs[0]
        loc = pjoin(os.path.dirname(pkg.ebuild.path), "metadata.xml")
        for report in self.check_file(loc):
            reporter.add_report(report(loc, pkg.category, pkg.package))


class CategoryMetadataXmlCheck(base_check):
    """category level metadata.xml scans"""

    feed_type = base.category_feed
    scope = base.category_scope
    misformed_error = CatBadlyFormedXml
    invalid_error = CatInvalidXml
    missing_error = CatMissingMetadataXml
    catref_error = CatMetadataXmlInvalidCatRef
    pkgref_error = CatMetadataXmlInvalidPkgRef
    indent_error = CatMetadataXmlIndentation

    known_results = (
        CatBadlyFormedXml, CatInvalidXml, CatMissingMetadataXml,
        CatMetadataXmlInvalidPkgRef, CatMetadataXmlInvalidCatRef,
        CatMetadataXmlIndentation)

    def feed(self, pkgs, reporter):
        # empty category, skipping check
        if not pkgs:
            return
        pkg = pkgs[0]
        loc = os.path.join(self.repo_base, pkg.category, "metadata.xml")
        for report in self.check_file(loc):
            reporter.add_report(report(loc, pkg.category))


def noop_validator(loc):
    return 0
