import argparse
from functools import partial
from itertools import chain
from lxml import etree
import os
from urllib.request import urlopen
from urllib import error as urllib_error

from pkgcore import const as pkgcore_const
from pkgcore.ebuild.atom import atom, MalformedAtom
from snakeoil import fileutils
from snakeoil.cli.exceptions import UserException
from snakeoil.osutils import pjoin
from snakeoil.strings import pluralism as _pl

from .. import base
from ..log import logger


class XsdError(Exception):
    """Problem acquiring an XML schema file required for a check."""


class _MissingXml(base.Error):
    """Required XML file is missing."""

    def __init__(self, filename):
        super().__init__()
        self.filename = os.path.basename(filename)

    @property
    def short_desc(self):
        return f'{self._attr} is missing {self.filename}'


class _BadlyFormedXml(base.Warning):
    """XML isn't well formed."""

    def __init__(self, filename, error):
        super().__init__()
        self.filename = os.path.basename(filename)
        self.error = error

    @property
    def short_desc(self):
        return f'{self._attr} {self.filename} is not well formed xml: {self.error}'


class _InvalidXml(base.Error):
    """XML fails XML Schema validation."""

    def __init__(self, filename, message):
        super().__init__()
        self.filename = os.path.basename(filename)
        self.message = message

    @staticmethod
    def format_lxml_errors(error_log):
        for l in error_log:
            yield f'line {l.line}, col {l.column}: ({l.type_name}) {l.message}'

    @property
    def short_desc(self):
        message = '\n'.join(self.format_lxml_errors(self.message))
        return f'{self._attr} {self.filename} violates metadata.xsd:\n{message}'


class _MetadataXmlInvalidPkgRef(base.Error):
    """metadata.xml <pkg/> references unknown/invalid package."""

    def __init__(self, filename, pkgtext):
        super().__init__()
        self.filename = os.path.basename(filename)
        self.pkgtext = pkgtext

    @property
    def short_desc(self):
        return (
            f'{self._attr} {self.filename} <pkg/> '
            f'references unknown/invalid package: {self.pkgtext!r}'
        )


class _MetadataXmlInvalidCatRef(base.Error):
    """metadata.xml <cat/> references unknown/invalid category."""

    def __init__(self, filename, cattext):
        super().__init__()
        self.filename = os.path.basename(filename)
        self.cattext = cattext

    @property
    def short_desc(self):
        return (
            f'{self._attr} {self.filename} <cat/> references '
            f'unknown/invalid category: {self.cattext!r}'
        )


class EmptyMaintainer(base.PackageResult, base.Warning):
    """Package with neither a maintainer or maintainer-needed comment in metadata.xml."""

    def __init__(self, filename, pkg):
        super().__init__(pkg)
        self.filename = filename

    @property
    def short_desc(self):
        return 'no package maintainer or maintainer-needed comment specified'


class MaintainerWithoutProxy(base.PackageResult, base.Warning):
    """Package has a proxied maintainer without a proxy.

    All package maintainers have non-@gentoo.org e-mail addresses. Most likely,
    this means that the package is maintained by a proxied maintainer but there
    is no explicit proxy (developer or project) listed. This means no Gentoo
    developer will be CC-ed on bug reports, and most likely no developer
    oversees the proxied maintainer's activity.
    """

    def __init__(self, pkg, filename, maintainers):
        super().__init__(pkg)
        self.filename = filename
        self.maintainers = tuple(maintainers)

    @property
    def short_desc(self):
        return (
            f"proxied maintainer{_pl(self.maintainers)} missing proxy dev/project: "
            f"[ {', '.join(map(str, self.maintainers))} ]")


class StaleProxyMaintProject(base.PackageResult, base.Warning):
    """Package lists proxy-maint project but has no proxied maintainers.

    The package explicitly lists proxy-maint@g.o as the only maintainer.
    Most likely, this means that the proxied maintainer has been removed
    but proxy-maint was left over.
    """

    def __init__(self, pkg, filename):
        super().__init__(pkg)
        self.filename = filename

    @property
    def short_desc(self):
        return "proxy-maint maintainer with no proxies"


class NonexistentProjectMaintainer(base.PackageResult, base.Warning):
    """Package specifying nonexistent project as a maintainer."""

    def __init__(self, pkg, filename, emails):
        super().__init__(pkg)
        self.filename = filename
        self.emails = tuple(emails)

    @property
    def short_desc(self):
        emails = ', '.join(sorted(self.emails))
        return f'nonexistent project maintainer{_pl(self.emails)}: [ {emails} ]'


class WrongMaintainerType(base.PackageResult, base.Warning):
    """A person-type maintainer matches an existing project."""

    def __init__(self, pkg, filename, emails):
        super().__init__(pkg)
        self.filename = filename
        self.emails = tuple(emails)

    @property
    def short_desc(self):
        emails = ', '.join(sorted(self.emails))
        return f'project maintainer{_pl(self.emails)} with type="person": [ {emails} ]'


class PkgMissingMetadataXml(base.PackageResult, _MissingXml):
    """Package is missing metadata.xml."""


class CatMissingMetadataXml(base.CategoryResult, _MissingXml):
    """Category is missing metadata.xml."""


class PkgInvalidXml(base.PackageResult, _InvalidXml):
    """Invalid package metadata.xml."""


class CatInvalidXml(base.CategoryResult, _InvalidXml):
    """Invalid category metadata.xml."""


class PkgBadlyFormedXml(base.PackageResult, _BadlyFormedXml):
    """Badly formed package metadata.xml."""


class CatBadlyFormedXml(base.CategoryResult, _BadlyFormedXml):
    """Badly formed category metadata.xml."""


class PkgMetadataXmlInvalidPkgRef(base.PackageResult, _MetadataXmlInvalidPkgRef):
    """Invalid package reference in package metadata.xml."""


class CatMetadataXmlInvalidPkgRef(base.CategoryResult, _MetadataXmlInvalidPkgRef):
    """Invalid package reference in category metadata.xml."""


class PkgMetadataXmlInvalidCatRef(base.PackageResult, _MetadataXmlInvalidCatRef):
    """Invalid category reference in package metadata.xml."""


class CatMetadataXmlInvalidCatRef(base.CategoryResult, _MetadataXmlInvalidCatRef):
    """Invalid category reference in category metadata.xml."""


class _MetadataXmlIndentation(base.Warning):
    """Inconsistent indentation in metadata.xml file.

    Either all tabs or all spaces should be used, not a mixture of both.
    """

    def __init__(self, filename, lines):
        super().__init__()
        self.filename = filename
        self.lines = lines

    @property
    def short_desc(self):
        return "metadata.xml has inconsistent indentation"

    @property
    def long_desc(self):
        return "%s on line%s %s" % (
            self.short_desc, _pl(self.lines), ', '.join(str(x) for x in self.lines))


class CatMetadataXmlIndentation(base.CategoryResult, _MetadataXmlIndentation):
    """Inconsistent indentation in category metadata.xml file.

    Either all tabs or all spaces should be used, not a mixture of both.
    """

class PkgMetadataXmlIndentation(base.PackageResult, _MetadataXmlIndentation):
    """Inconsistent indentation in package metadata.xml file.

    Either all tabs or all spaces should be used, not a mixture of both.
    """


class _MetadataXmlEmptyElement(base.Warning):
    """Empty element in metadata.xml file."""

    def __init__(self, filename, element, line):
        super().__init__()
        self.filename = filename
        self.element = element
        self.line = line

    @property
    def short_desc(self):
        return f"metadata.xml has empty element {self.element!r} on line {self.line}"


class CatMetadataXmlEmptyElement(base.CategoryResult, _MetadataXmlEmptyElement):
    """Empty element in category metadata.xml file."""


class PkgMetadataXmlEmptyElement(base.PackageResult, _MetadataXmlEmptyElement):
    """Empty element in package metadata.xml file."""


class _XmlBaseCheck(base.Check):
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
                '--metadata-xsd-required', action='store_true',
                help="if metadata.xsd cannot be fetched (no connection for example), "
                     "treat it as a failure rather than warning and ignoring.")
        except argparse.ArgumentError:
            # the arguments have already been added to the parser
            pass

    def __init__(self, options):
        super().__init__(options)
        self.repo_base = options.target_repo.location
        self.pkgref_cache = {}

    def _fetch_xsd(self):
        if self.options.verbosity > 0:
            logger.warn(
                'metadata.xsd cannot be opened from '
                f'{metadata_xsd!r}, will refetch')
        logger.info(f"fetching metdata.xsd from {self.xsd_url}")

        try:
            xsd_data = urlopen(self.xsd_url).read()
        except urllib_error.URLError as e:
            msg = f'failed fetching XML schema from {self.xsd_url}: {e.reason}'
            if self.options.metadata_xsd_required:
                raise UserException(msg)
            self.validator = noop_validator
            raise XsdError(msg)

        metadata_xsd = pjoin(
            base.CACHE_DIR, 'repos', 'gentoo', os.path.basename(self.xsd_url))
        try:
            os.makedirs(os.path.dirname(metadata_xsd), exist_ok=True)
            fileutils.write_file(metadata_xsd, 'wb', xsd_data)
        except EnvironmentError as e:
            msg = f'failed saving XML schema to {metadata_xsd!r}: {e}'
            if self.options.metadata_xsd_required:
                raise UserException(msg)
            self.validator = noop_validator
            raise XsdError(msg)
        return metadata_xsd

    def start(self):
        # try to use repo-bundled version of metadata.xsd and fallback to
        # version installed with pkgcore
        metadata_xsd = pjoin(self.repo_base, 'metadata', 'xml-schema', 'metadata.xsd')
        if not os.path.isfile(metadata_xsd):
            metadata_xsd = pjoin(pkgcore_const.DATA_PATH, 'xml-schema', 'metadata.xsd')

        if _XmlBaseCheck.schema is None:
            if not os.path.isfile(metadata_xsd):
                try:
                    metadata_xsd = self._fetch_xsd()
                except XsdError as e:
                    logger.warn(f'skipping check: {e}')
                    return
            _XmlBaseCheck.schema = etree.XMLSchema(etree.parse(metadata_xsd))

    def feed(self, thing):
        raise NotImplementedError(self.feed)

    def check_doc(self, pkg, loc, doc):
        """Perform additional document structure checks."""
        # find all root descendant elements that are empty
        for el in doc.getroot().iterdescendants():
            if (not el.getchildren() and (el.text is None or not el.text.strip())
                    and not el.tag == 'stabilize-allarches'):
                yield self.empty_element(pkg, loc, el.tag, el.sourceline)

        for el in doc.findall('.//cat'):
            c = el.text.strip()
            if c not in self.options.search_repo.categories:
                yield self.catref_error(pkg, loc, c)

        for el in doc.findall('.//pkg'):
            p = el.text.strip()
            if p not in self.pkgref_cache:
                try:
                    a = atom(p)
                    found = self.options.search_repo.has_match(a)
                except MalformedAtom:
                    found = False
                self.pkgref_cache[p] = found

            if not self.pkgref_cache[p]:
                yield self.pkgref_error(pkg, loc, p)

    def check_whitespace(self, pkg, loc):
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
            yield self.indent_error(pkg, loc, indents)

    def check_file(self, loc, pkg):
        repo = pkg.repo
        try:
            doc = etree.parse(loc)
        except (IOError, OSError):
            # it's only an error when missing in the main gentoo repo
            if repo.repo_id == 'gentoo':
                yield self.missing_error(pkg, loc)
            return
        except etree.XMLSyntaxError as e:
            yield self.misformed_error(pkg, loc, str(e))
            return

        # note: while doc is available, do not pass it here as it may
        # trigger undefined behavior due to incorrect structure
        if self.schema is not None and not self.schema.validate(doc):
            yield self.invalid_error(pkg, loc, self.schema.error_log)
            return

        # check for missing maintainer-needed comments in gentoo repo
        # and incorrect maintainers
        if pkg is not None and pkg.repo.repo_id == 'gentoo':
            if pkg.maintainers:
                if not any(m.email.endswith('@gentoo.org')
                           for m in pkg.maintainers):
                    yield MaintainerWithoutProxy(pkg, loc, pkg.maintainers)
                elif (len(pkg.maintainers) == 1 and
                      any(m.email == 'proxy-maint@gentoo.org'
                          for m in pkg.maintainers)):
                    yield StaleProxyMaintProject(pkg, loc)
            else:
                if not any(c.text.strip() == 'maintainer-needed'
                           for c in doc.xpath('//comment()')):
                    yield EmptyMaintainer(pkg, loc)

            # check maintainer validity
            projects = frozenset(pkg.repo.projects_xml.projects)
            if projects:
                nonexistent = []
                wrong_maintainers = []
                for m in pkg.maintainers:
                    if m.maint_type == 'project' and m.email not in projects:
                        nonexistent.append(m.email)
                    elif m.maint_type == 'person' and m.email in projects:
                        wrong_maintainers.append(m.email)
                if nonexistent:
                    yield NonexistentProjectMaintainer(pkg, loc, nonexistent)
                if wrong_maintainers:
                    yield WrongMaintainerType(pkg, loc, wrong_maintainers)

        yield from self.check_doc(pkg, loc, doc)
        yield from self.check_whitespace(pkg, loc)


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
        MaintainerWithoutProxy, StaleProxyMaintProject,
        NonexistentProjectMaintainer, WrongMaintainerType)

    def feed(self, pkgs):
        # package with no ebuilds, skipping check
        if not pkgs:
            return
        pkg = pkgs[0]
        loc = pjoin(os.path.dirname(pkg.ebuild.path), "metadata.xml")
        yield from self.check_file(loc, pkg)


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
        yield from self.check_file(loc, pkg)


def noop_validator(loc):
    return 0
