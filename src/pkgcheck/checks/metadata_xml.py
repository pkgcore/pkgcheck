import os

from snakeoil.demandload import demandload
from snakeoil.strings import pluralism as _pl

from .. import base

demandload(
    'argparse',
    'functools:partial',
    'itertools:chain',
    'urllib.request:urlopen',
    'urllib:error@urllib_error',
    'lxml:etree',
    'tempfile:NamedTemporaryFile',
    'pkgcore.ebuild.atom:atom',
    'pkgcore.log:logger',
    'snakeoil.osutils:pjoin',
    'snakeoil:fileutils',
)


class _MissingXml(base.Error):
    """Required XML file is missing."""

    __slots__ = ('category', 'package', 'filename')
    __attrs__ = __slots__

    def __init__(self, filename, category, package=None):
        super().__init__()
        self.category = category
        self.package = package
        self.filename = filename

    @property
    def _label(self):
        if self.package is not None:
            return f"{self.category}/{self.package}"
        return self.category

    @property
    def short_desc(self):
        return f"{self._label} is missing {os.path.basename(self.filename)}"


class _BadlyFormedXml(base.Warning):
    """XML isn't well formed."""

    __slots__ = ("category", "package", "filename")
    __attrs__ = __slots__

    def __init__(self, filename, category, package=None):
        super().__init__()
        self.category = category
        self.package = package
        self.filename = filename

    @property
    def _label(self):
        if self.package is not None:
            return f"{self.category}/{self.package}"
        return self.category

    @property
    def short_desc(self):
        return f"{self._label} {os.path.basename(self.filename)} is not well formed xml"


class _InvalidXml(base.Error):
    """XML fails XML Schema validation."""

    __slots__ = ("category", "package", "filename")
    __attrs__ = __slots__

    # message first so partial() can be easily applied
    def __init__(self, message, filename, category, package=None):
        super().__init__()
        self.message = message
        self.category = category
        self.package = package
        self.filename = filename

    @property
    def _label(self):
        if self.package is not None:
            return f"{self.category}/{self.package}"
        return self.category

    @staticmethod
    def format_lxml_errors(error_log):
        for l in error_log:
            yield f'line {l.line}, col {l.column}: ({l.type_name}) {l.message}'

    @property
    def short_desc(self):
        return "%s %s violates metadata.xsd:\n%s" % (
            self._label, os.path.basename(self.filename),
            '\n'.join(self.format_lxml_errors(self.message)))


class _MetadataXmlInvalidPkgRef(base.Error):
    """metadata.xml <pkg/> references unknown/invalid package."""

    __slots__ = ("category", "package", "filename")
    __attrs__ = __slots__

    def __init__(self, pkgtext, filename, category, package=None):
        super().__init__()
        self.category = category
        self.package = package
        self.filename = filename
        self.pkgtext = pkgtext

    @property
    def _label(self):
        if self.package is not None:
            return f"{self.category}/{self.package}"
        return self.category

    @property
    def short_desc(self):
        return "%s %s <pkg/> references unknown/invalid package: %r" % (
            self._label, os.path.basename(self.filename), self.pkgtext)


class _MetadataXmlInvalidCatRef(base.Error):
    """metadata.xml <cat/> references unknown/invalid category"""

    __slots__ = ("category", "package", "filename")
    __attrs__ = __slots__

    def __init__(self, cattext, filename, category, package=None):
        super().__init__()
        self.category = category
        self.package = package
        self.filename = filename
        self.cattext = cattext

    @property
    def _label(self):
        if self.package is not None:
            return f"{self.category}/{self.package}"
        return self.category

    @property
    def short_desc(self):
        return "%s %s <cat/> references unknown/invalid category: %r" % (
            self._label, os.path.basename(self.filename), self.cattext)


class EmptyMaintainer(base.Warning):
    """Package with neither a maintainer or maintainer-needed comment in metadata.xml."""

    __slots__ = ("category", "package", "filename")
    threshold = base.package_feed

    def __init__(self, filename, category, package):
        super().__init__()
        self.filename = filename
        self.category = category
        self.package = package

    @property
    def short_desc(self):
        return 'no package maintainer or maintainer-needed comment specified'


class MaintainerWithoutProxy(base.Warning):
    """Package has a proxied maintainer without a proxy.

    All package maintainers have non-@gentoo.org e-mail addresses. Most likely,
    this means that the package is maintained by a proxied maintainer but there
    is no explicit proxy (developer or project) listed. This means no Gentoo
    developer will be CC-ed on bug reports, and most likely no developer
    oversees the proxied maintainer's activity.
    """

    __slots__ = ("category", "package", "filename", "maintainers")
    threshold = base.package_feed

    def __init__(self, maintainers, filename, category, package):
        super().__init__()
        self.maintainers = tuple(maintainers)
        self.filename = filename
        self.category = category
        self.package = package

    @property
    def short_desc(self):
        return (
            f"proxied maintainer{_pl(self.maintainers)} missing proxy dev/project: "
            f"[ {', '.join(map(str, self.maintainers))} ]")


class StaleProxyMaintProject(base.Warning):
    """Package lists proxy-maint project but has no proxied maintainers.

    The package explicitly lists proxy-maint@g.o as the only maintainer.
    Most likely, this means that the proxied maintainer has been removed
    but proxy-maint was left over.
    """

    __slots__ = ("category", "package", "filename")
    threshold = base.package_feed

    def __init__(self, filename, category, package):
        super().__init__()
        self.filename = filename
        self.category = category
        self.package = package

    @property
    def short_desc(self):
        return "proxy-maint maintainer with no proxies"


class PkgMissingMetadataXml(_MissingXml):
    """Package is missing metadata.xml."""
    __slots__ = ()
    threshold = base.package_feed


class CatMissingMetadataXml(_MissingXml):
    """Category is missing metadata.xml."""
    __slots__ = ()
    threshold = base.category_feed


class PkgInvalidXml(_InvalidXml):
    """Invalid package metadata.xml."""
    __slots__ = ()
    threshold = base.package_feed


class CatInvalidXml(_InvalidXml):
    """Invalid category metadata.xml."""
    __slots__ = ()
    threshold = base.category_feed


class PkgBadlyFormedXml(_BadlyFormedXml):
    """Badly formed package metadata.xml."""
    __slots__ = ()
    threshold = base.package_feed


class CatBadlyFormedXml(_BadlyFormedXml):
    """Badly formed category metadata.xml."""
    __slots__ = ()
    threshold = base.category_feed


class PkgMetadataXmlInvalidPkgRef(_MetadataXmlInvalidPkgRef):
    """Invalid package reference in package metadata.xml."""
    __slots__ = ()
    threshold = base.package_feed


class CatMetadataXmlInvalidPkgRef(_MetadataXmlInvalidPkgRef):
    """Invalid package reference in category metadata.xml."""
    __slots__ = ()
    threshold = base.category_feed


class PkgMetadataXmlInvalidCatRef(_MetadataXmlInvalidCatRef):
    """Invalid category reference in package metadata.xml."""
    __slots__ = ()
    threshold = base.package_feed


class CatMetadataXmlInvalidCatRef(_MetadataXmlInvalidCatRef):
    """Invalid category reference in category metadata.xml."""
    __slots__ = ()
    threshold = base.category_feed


class _MetadataXmlIndentation(base.Warning):
    """Inconsistent indentation in metadata.xml file.

    Either all tabs or all spaces should be used, not a mixture of both.
    """

    __slots__ = ("category", "package", "filename", "lines")
    __attrs__ = __slots__

    def __init__(self, lines, filename, category, package=None):
        super().__init__()
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
            self.short_desc, _pl(self.lines), ', '.join(str(x) for x in self.lines))


class CatMetadataXmlIndentation(_MetadataXmlIndentation):
    """Inconsistent indentation in category metadata.xml file.

    Either all tabs or all spaces should be used, not a mixture of both.
    """
    __slots__ = ()
    threshold = base.category_feed

class PkgMetadataXmlIndentation(_MetadataXmlIndentation):
    """Inconsistent indentation in package metadata.xml file.

    Either all tabs or all spaces should be used, not a mixture of both.
    """
    __slots__ = ()
    threshold = base.package_feed


class _MetadataXmlEmptyElement(base.Warning):
    """Empty element in metadata.xml file."""

    __slots__ = ("category", "package", "filename", "line", "element")
    __attrs__ = __slots__

    def __init__(self, element, line, filename, category, package=None):
        super().__init__()
        self.element = element
        self.line = line
        self.filename = filename
        self.category = category
        self.package = package

    @property
    def short_desc(self):
        return f"metadata.xml has empty element {self.element!r} on line {self.line}"


class CatMetadataXmlEmptyElement(_MetadataXmlEmptyElement):
    """Empty element in category metadata.xml file."""
    __slots__ = ()
    threshold = base.category_feed


class PkgMetadataXmlEmptyElement(_MetadataXmlEmptyElement):
    """Empty element in package metadata.xml file."""
    __slots__ = ()
    threshold = base.package_feed


class _XmlBaseCheck(base.Template):
    """Base class for metadata.xml scans."""

    xsd_url = "https://www.gentoo.org/xml-schema/metadata.xsd"
    schema = None

    misformed_error = None
    invalid_error = None
    missing_error = None

    @classmethod
    def mangle_argparser(cls, parser):
        try:
            parser.plugin.add_argument(
                '--metadata-xsd',
                help=f'location to cache {cls.xsd_url}')
            parser.plugin.add_argument(
                '--metadata-xsd-required',
                help="if metadata.xsd cannot be fetched (no connection for example), "
                     "treat it as a failure rather than warning and ignoring.")
        except argparse.ArgumentError:
            # the arguments have already been added to the parser
            pass

    def __init__(self, options):
        super().__init__(options)
        self.repo_base = options.target_repo.location
        self.xsd_file = None

    def start(self):
        self.pkgref_cache = {}

        if _XmlBaseCheck.schema is None:
            refetch = False
            write_path = read_path = self.options.metadata_xsd
            if write_path is None:
                read_path = pjoin(self.repo_base, 'metadata', 'xml-schema', 'metadata.xsd')
            refetch = not os.path.isfile(read_path)

            if refetch:
                if self.options.verbosity > 0:
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

            _XmlBaseCheck.schema = etree.XMLSchema(etree.parse(read_path))

    def feed(self, thing):
        raise NotImplementedError(self.feed)

    def check_doc(self, doc):
        """Perform additional document structure checks."""
        # find all root descendant elements that are empty
        for el in doc.getroot().iterdescendants():
            if (not el.getchildren() and (el.text is None or not el.text.strip())
                    and not el.tag == 'stabilize-allarches'):
                yield partial(self.empty_element, el.tag, el.sourceline)

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
        """Check for indentation consistency."""
        orig_indent = None
        indents = set()
        with open(loc) as f:
            for lineno, line in enumerate(f, 1):
                for i in line[:-len(line.lstrip())]:
                    if i != orig_indent:
                        if orig_indent is None:
                            orig_indent = i
                        else:
                            indents.update([lineno])
        if indents:
            yield partial(self.indent_error, indents)

    def check_file(self, loc, repo, pkg=None):
        try:
            doc = etree.parse(loc)
        except (IOError, OSError):
            # it's only an error when missing in the main gentoo repo
            if repo.repo_id == 'gentoo':
                return (self.missing_error,)
            return ()
        except etree.XMLSyntaxError:
            return (self.misformed_error,)

        # note: while doc is available, do not pass it here as it may
        # trigger undefined behavior due to incorrect structure
        if self.schema is not None and not self.schema.validate(doc):
            return (partial(self.invalid_error, self.schema.error_log),)

        # check for missing maintainer-needed comments in gentoo repo
        # and incorrect maintainers
        maintainers = []
        if pkg is not None and pkg.repo.repo_id == 'gentoo':
            if pkg.maintainers:
                if not any(m.email.endswith('@gentoo.org')
                           for m in pkg.maintainers):
                    maintainers.append(partial(
                        MaintainerWithoutProxy, pkg.maintainers))
                elif (len(pkg.maintainers) == 1 and
                      any(m.email == 'proxy-maint@gentoo.org'
                          for m in pkg.maintainers)):
                    maintainers.append(partial(StaleProxyMaintProject))
            else:
                if not any(c.text.strip() == 'maintainer-needed'
                           for c in doc.xpath('//comment()')):
                    maintainers.append(partial(EmptyMaintainer))

        keywords = (maintainers, self.check_doc(doc), self.check_whitespace(loc))
        return chain.from_iterable(keywords)


class PackageMetadataXmlCheck(_XmlBaseCheck):
    """Package level metadata.xml scans."""

    feed_type = base.package_feed
    scope = base.package_scope
    misformed_error = PkgBadlyFormedXml
    invalid_error = PkgInvalidXml
    missing_error = PkgMissingMetadataXml
    catref_error = PkgMetadataXmlInvalidCatRef
    pkgref_error = PkgMetadataXmlInvalidPkgRef
    indent_error = PkgMetadataXmlIndentation
    empty_element = PkgMetadataXmlEmptyElement

    known_results = (
        PkgBadlyFormedXml, PkgInvalidXml, PkgMissingMetadataXml,
        PkgMetadataXmlInvalidPkgRef, PkgMetadataXmlInvalidCatRef,
        PkgMetadataXmlIndentation, PkgMetadataXmlEmptyElement, EmptyMaintainer,
        MaintainerWithoutProxy, StaleProxyMaintProject)

    def feed(self, pkgs):
        # package with no ebuilds, skipping check
        if not pkgs:
            return
        pkg = pkgs[0]

        loc = pjoin(os.path.dirname(pkg.ebuild.path), "metadata.xml")
        for report in self.check_file(loc, pkg.repo, pkg):
            yield report(loc, pkg.category, pkg.package)


class CategoryMetadataXmlCheck(_XmlBaseCheck):
    """Category level metadata.xml scans."""

    feed_type = base.category_feed
    scope = base.category_scope
    misformed_error = CatBadlyFormedXml
    invalid_error = CatInvalidXml
    missing_error = CatMissingMetadataXml
    catref_error = CatMetadataXmlInvalidCatRef
    pkgref_error = CatMetadataXmlInvalidPkgRef
    indent_error = CatMetadataXmlIndentation
    empty_element = CatMetadataXmlEmptyElement

    known_results = (
        CatBadlyFormedXml, CatInvalidXml, CatMissingMetadataXml,
        CatMetadataXmlInvalidPkgRef, CatMetadataXmlInvalidCatRef,
        CatMetadataXmlIndentation, CatMetadataXmlEmptyElement)

    def feed(self, pkgs):
        # empty category, skipping check
        if not pkgs:
            return
        pkg = pkgs[0]
        loc = os.path.join(self.repo_base, pkg.category, "metadata.xml")
        for report in self.check_file(loc, pkg.repo):
            yield report(loc, pkg.category)


def noop_validator(loc):
    return 0
