import os
import re
from difflib import SequenceMatcher
from itertools import chain

from lxml import etree
from pkgcore import const as pkgcore_const
from pkgcore.ebuild.atom import MalformedAtom, atom
from pkgcore.restrictions.packages import Conditional
from pkgcore.fetch import fetchable
from snakeoil.osutils import pjoin
from snakeoil.sequences import iflatten_instance
from snakeoil.strings import pluralism

from .. import results, sources
from . import Check


class _MissingXml(results.Error):
    """Required XML file is missing."""

    def __init__(self, filename, **kwargs):
        super().__init__(**kwargs)
        self.filename = filename

    @property
    def desc(self):
        return f"{self._attr} is missing {self.filename}"


class _BadlyFormedXml(results.Error):
    """XML isn't well formed."""

    def __init__(self, filename, error, **kwargs):
        super().__init__(**kwargs)
        self.filename = filename
        self.error = error

    @property
    def desc(self):
        return f"{self._attr} {self.filename} is not well formed xml: {self.error}"


class _InvalidXml(results.Error):
    """XML fails XML Schema validation."""

    def __init__(self, filename, message, **kwargs):
        super().__init__(**kwargs)
        self.filename = filename
        self.message = message

    @property
    def desc(self):
        return f"{self._attr} {self.filename} violates metadata.xsd:\n{self.message}"


class _MetadataXmlInvalidPkgRef(results.Error):
    """metadata.xml <pkg/> references unknown/invalid package."""

    def __init__(self, filename, pkgtext, **kwargs):
        super().__init__(**kwargs)
        self.filename = filename
        self.pkgtext = pkgtext

    @property
    def desc(self):
        return (
            f"{self._attr} {self.filename} <pkg/> "
            f"references unknown/invalid package: {self.pkgtext!r}"
        )


class _MetadataXmlInvalidCatRef(results.Error):
    """metadata.xml <cat/> references unknown/invalid category."""

    def __init__(self, filename, cattext, **kwargs):
        super().__init__(**kwargs)
        self.filename = filename
        self.cattext = cattext

    @property
    def desc(self):
        return (
            f"{self._attr} {self.filename} <cat/> references "
            f"unknown/invalid category: {self.cattext!r}"
        )


class MaintainerNeeded(results.PackageResult, results.Warning):
    """Package with missing or invalid maintainer-needed comment in metadata.xml."""

    def __init__(self, filename, needed, **kwargs):
        super().__init__(**kwargs)
        self.filename = filename
        self.needed = needed

    @property
    def desc(self):
        if not self.needed:
            return f"{self.filename}: missing maintainer-needed comment"
        return f"{self.filename}: invalid maintainer-needed comment"


class MaintainerWithoutProxy(results.PackageResult, results.Warning):
    """Package has a proxied maintainer without a proxy.

    All package maintainers have non-@gentoo.org e-mail addresses. Most likely,
    this means that the package is maintained by a proxied maintainer but there
    is no explicit proxy (developer or project) listed. This means no Gentoo
    developer will be CC-ed on bug reports, and most likely no developer
    oversees the proxied maintainer's activity.
    """

    def __init__(self, filename, maintainers, **kwargs):
        super().__init__(**kwargs)
        self.filename = filename
        self.maintainers = tuple(maintainers)

    @property
    def desc(self):
        s = pluralism(self.maintainers)
        maintainers = ", ".join(self.maintainers)
        return f"{self.filename}: proxied maintainer{s} missing proxy dev/project: {maintainers}"


class ProxyWithoutProxied(results.PackageResult, results.Warning):
    """Package lists a proxy with no proxied maintainers.

    The package explicitly lists a proxy with no proxied maintainers.
    Most likely, this means that the proxied maintainer has been removed
    but the proxy was accidentally left.
    """

    def __init__(self, filename, **kwargs):
        super().__init__(**kwargs)
        self.filename = filename

    @property
    def desc(self):
        return f"{self.filename}: proxy with no proxied maintainer"


class NonexistentProjectMaintainer(results.PackageResult, results.Warning):
    """Package specifying nonexistent project as a maintainer."""

    def __init__(self, filename, emails, **kwargs):
        super().__init__(**kwargs)
        self.filename = filename
        self.emails = tuple(emails)

    @property
    def desc(self):
        s = pluralism(self.emails)
        emails = ", ".join(self.emails)
        return f"{self.filename}: nonexistent project maintainer{s}: {emails}"


class WrongMaintainerType(results.PackageResult, results.Warning):
    """A person-type maintainer matches an existing project."""

    def __init__(self, filename, emails, **kwargs):
        super().__init__(**kwargs)
        self.filename = filename
        self.emails = tuple(emails)

    @property
    def desc(self):
        s = pluralism(self.emails)
        emails = ", ".join(self.emails)
        return f'{self.filename}: project maintainer{s} with type="person": {emails}'


class PkgMissingMetadataXml(_MissingXml, results.PackageResult):
    """Package is missing metadata.xml."""


class CatMissingMetadataXml(_MissingXml, results.CategoryResult):
    """Category is missing metadata.xml."""


class PkgInvalidXml(_InvalidXml, results.PackageResult):
    """Invalid package metadata.xml."""


class CatInvalidXml(_InvalidXml, results.CategoryResult):
    """Invalid category metadata.xml."""


class PkgBadlyFormedXml(_BadlyFormedXml, results.PackageResult):
    """Badly formed package metadata.xml."""


class CatBadlyFormedXml(_BadlyFormedXml, results.CategoryResult):
    """Badly formed category metadata.xml."""


class PkgMetadataXmlInvalidPkgRef(_MetadataXmlInvalidPkgRef, results.PackageResult):
    """Invalid package reference in package metadata.xml."""


class CatMetadataXmlInvalidPkgRef(_MetadataXmlInvalidPkgRef, results.CategoryResult):
    """Invalid package reference in category metadata.xml."""


class PkgMetadataXmlInvalidCatRef(_MetadataXmlInvalidCatRef, results.PackageResult):
    """Invalid category reference in package metadata.xml."""


class CatMetadataXmlInvalidCatRef(_MetadataXmlInvalidCatRef, results.CategoryResult):
    """Invalid category reference in category metadata.xml."""


class _MetadataXmlIndentation(results.BaseLinesResult, results.Style):
    """Inconsistent indentation in metadata.xml file.

    Either all tabs or all spaces should be used, not a mixture of both.
    """

    def __init__(self, filename, **kwargs):
        super().__init__(**kwargs)
        self.filename = filename

    @property
    def desc(self):
        return f"{self.filename}: metadata.xml has inconsistent indentation {self.lines_str}"


class CatMetadataXmlIndentation(_MetadataXmlIndentation, results.CategoryResult):
    """Inconsistent indentation in category metadata.xml file.

    Either all tabs or all spaces should be used, not a mixture of both.
    """


class PkgMetadataXmlIndentation(_MetadataXmlIndentation, results.PackageResult):
    """Inconsistent indentation in package metadata.xml file.

    Either all tabs or all spaces should be used, not a mixture of both.
    """


class _MetadataXmlEmptyElement(results.Style):
    """Empty element in metadata.xml file."""

    def __init__(self, filename, element, line, **kwargs):
        super().__init__(**kwargs)
        self.filename = filename
        self.element = element
        self.line = line

    @property
    def desc(self):
        return f"{self.filename}: empty element {self.element!r} on line {self.line}"


class CatMetadataXmlEmptyElement(_MetadataXmlEmptyElement, results.CategoryResult):
    """Empty element in category metadata.xml file."""


class PkgMetadataXmlEmptyElement(_MetadataXmlEmptyElement, results.PackageResult):
    """Empty element in package metadata.xml file."""


class RedundantLongDescription(results.PackageResult, results.Style):
    """Package's longdescription element in metadata.xml and DESCRIPTION are interchangeable.

    The longdescription element is for providing extended information that
    doesn't fit in DESCRIPTION.
    """

    def __init__(self, msg, **kwargs):
        super().__init__(**kwargs)
        self.msg = msg

    @property
    def desc(self):
        return self.msg


class InvalidRemoteID(results.PackageResult, results.Warning):
    """Package's remote-id value incorrect for the specified type."""

    def __init__(self, id_type, id_value, expected, **kwargs):
        super().__init__(**kwargs)
        self.id_type = id_type
        self.id_value = id_value
        self.expected = expected

    @property
    def desc(self):
        return (
            f"remote-id value {self.id_value!r} invalid for "
            f"type={self.id_type!r}, expected: {self.expected!r}"
        )


class InvalidMetadataRestrict(results.PackageResult, results.Error):
    """Invalid package restrictions used in metadata.xml."""

    def __init__(self, restrict: str, msg: str, **kwargs):
        super().__init__(**kwargs)
        self.restrict = restrict
        self.msg = msg

    @property
    def desc(self):
        return f"metadata.xml: invalid package restrictions {self.restrict!r}: {self.msg}"


class _XmlBaseCheck(Check):
    """Base class for metadata.xml scans."""

    schema = None

    misformed_error = None
    invalid_error = None
    missing_error = None

    def __init__(self, *args):
        super().__init__(*args)
        self.repo_base = self.options.target_repo.location
        self.pkgref_cache = {}
        # content validation checks to run after parsing XML doc
        self._checks = tuple(getattr(self, x) for x in dir(self) if x.startswith("_check_"))

        # Prefer xsd file from the target repository or its masters, falling
        # back to the file installed with pkgcore.
        for repo in reversed(self.options.target_repo.trees):
            metadata_xsd = pjoin(repo.location, "metadata", "xml-schema", "metadata.xsd")
            if os.path.isfile(metadata_xsd):
                try:
                    self.schema = etree.XMLSchema(etree.parse(metadata_xsd))
                    break
                except etree.XMLSchemaParseError:
                    # ignore invalid xsd files
                    pass
        else:
            metadata_xsd = pjoin(pkgcore_const.DATA_PATH, "xml-schema", "metadata.xsd")
            self.schema = etree.XMLSchema(etree.parse(metadata_xsd))

    def _check_doc(self, pkg, loc, doc):
        """Perform additional document structure checks."""
        # Find all root descendant elements that are empty except
        # 'stabilize-allarches' which is allowed to be empty and 'flag' which
        # is caught by MissingLocalUseDesc.
        for el in doc.getroot().iterdescendants():
            if (
                not el.getchildren()
                and (el.text is None or not el.text.strip())
                and el.tag not in ("flag", "stabilize-allarches")
            ):
                yield self.empty_element(os.path.basename(loc), el.tag, el.sourceline, pkg=pkg)

        for el in doc.findall(".//cat"):
            c = el.text.strip()
            if c not in self.options.search_repo.categories:
                yield self.catref_error(os.path.basename(loc), c, pkg=pkg)

        for el in doc.findall(".//pkg"):
            p = el.text.strip()
            if p not in self.pkgref_cache:
                try:
                    a = atom(p)
                    found = self.options.search_repo.has_match(a)
                except MalformedAtom:
                    found = False
                self.pkgref_cache[p] = found

            if not self.pkgref_cache[p]:
                yield self.pkgref_error(os.path.basename(loc), p, pkg=pkg)

    def _check_whitespace(self, pkg, loc, doc):
        """Check for indentation consistency."""
        orig_indent = None
        indents = set()
        with open(loc) as f:
            for lineno, line in enumerate(f, 1):
                for i in line[: -len(line.lstrip())]:
                    if i != orig_indent:
                        if orig_indent is None:
                            orig_indent = i
                        else:
                            indents.add(lineno)
        if indents:
            yield self.indent_error(os.path.basename(loc), lines=map(str, sorted(indents)), pkg=pkg)

    @staticmethod
    def _format_lxml_errors(error_log):
        for x in error_log:
            yield f"line {x.line}, col {x.column}: ({x.type_name}) {x.message}"

    def _parse_xml(self, pkg, loc):
        try:
            doc = etree.parse(loc)
        except (IOError, OSError):
            # it's only an error when missing in the main gentoo repo
            if self.options.gentoo_repo:
                yield self.missing_error(os.path.basename(loc), pkg=pkg)
            return
        except etree.XMLSyntaxError as e:
            yield self.misformed_error(os.path.basename(loc), str(e), pkg=pkg)
            return

        # note: while doc is available, do not pass it here as it may
        # trigger undefined behavior due to incorrect structure
        if self.schema is not None and not self.schema.validate(doc):
            message = "\n".join(self._format_lxml_errors(self.schema.error_log))
            yield self.invalid_error(os.path.basename(loc), message, pkg=pkg)
            return

        # run all post parsing/validation checks
        for check in self._checks:
            yield from check(pkg, loc, doc)

    def feed(self, pkgset):
        pkg = pkgset[0]
        loc = self._get_xml_location(pkg)
        yield from self._parse_xml(pkg, loc)


class PackageMetadataXmlCheck(_XmlBaseCheck):
    """Package level metadata.xml scans."""

    _source = sources.PackageRepoSource
    misformed_error = PkgBadlyFormedXml
    invalid_error = PkgInvalidXml
    missing_error = PkgMissingMetadataXml
    catref_error = PkgMetadataXmlInvalidCatRef
    pkgref_error = PkgMetadataXmlInvalidPkgRef
    indent_error = PkgMetadataXmlIndentation
    empty_element = PkgMetadataXmlEmptyElement

    known_results = frozenset(
        [
            PkgBadlyFormedXml,
            PkgInvalidXml,
            PkgMissingMetadataXml,
            PkgMetadataXmlInvalidPkgRef,
            PkgMetadataXmlInvalidCatRef,
            PkgMetadataXmlIndentation,
            PkgMetadataXmlEmptyElement,
            MaintainerNeeded,
            MaintainerWithoutProxy,
            ProxyWithoutProxied,
            RedundantLongDescription,
            NonexistentProjectMaintainer,
            WrongMaintainerType,
            InvalidRemoteID,
            InvalidMetadataRestrict,
        ]
    )

    _one_component_validator_re = re.compile(r"^[^/]+$")
    _two_components_validator_re = re.compile(r"^[^/]+/[^/]+$")
    _gitlab_validator_re = re.compile(r"^([^/]+/)*[^/]+/[^/]+$")

    remote_id_validators = {
        # {name}-style remotes
        "cpan": (_one_component_validator_re, "{project}"),
        "cpan-module": (_one_component_validator_re, "{module}"),
        "cran": (_one_component_validator_re, "{project}"),
        "ctan": (_one_component_validator_re, "{project}"),
        "google-code": (_one_component_validator_re, "{project}"),
        "osdn": (_one_component_validator_re, "{project}"),
        "pear": (_one_component_validator_re, "{project}"),
        "pecl": (_one_component_validator_re, "{project}"),
        "pypi": (_one_component_validator_re, "{project}"),
        "rubygems": (_one_component_validator_re, "{project}"),
        "sourceforge": (_one_component_validator_re, "{project}"),
        # {name} with a special check for lp: prefix
        "launchpad": (re.compile(r"^(?!lp:)[^/]+$"), "{project}"),
        # {owner}/{name}-style remotes
        "bitbucket": (_two_components_validator_re, "{username}/{project}"),
        "codeberg": (_two_components_validator_re, "{username}/{project}"),
        "github": (_two_components_validator_re, "{username}/{project}"),
        # gitlab (2+ components)
        "gitlab": (_gitlab_validator_re, "{username}/[{group}/...]{repo}"),
        "heptapod": (_gitlab_validator_re, "{username}/[{group}/...]{repo}"),
        # cpe
        "cpe": (re.compile(r"^cpe:/[aho]:[^:]+:[^:]+$"), "cpe:/[aho]:{vendor}:{product}"),
        # 1+ component + no ".git" suffix
        "gentoo": (re.compile(r"^([^/]+/)*[^/]+(?<!\.git)$"), "[{group}/...]{repo}"),
        # a positive decimal number
        "vim": (re.compile(r"^[1-9]\d*$"), "{script_id}"),
    }

    @staticmethod
    def _maintainer_proxied_key(m):
        if m.proxied is not None:
            return m.proxied
        if m.email == "proxy-maint@gentoo.org":
            return "proxy"
        if m.email.endswith("@gentoo.org"):
            return "no"
        return "yes"

    def _check_maintainers(self, pkg, loc, doc):
        """Validate maintainers in package metadata for the gentoo repo."""
        if self.options.gentoo_repo:
            maintainer_needed = any(
                c.text.strip() == "maintainer-needed" for c in doc.xpath("//comment()")
            )
            if pkg.maintainers:
                # check for invalid maintainer-needed comment
                if maintainer_needed:
                    yield MaintainerNeeded(os.path.basename(loc), maintainer_needed, pkg=pkg)

                # determine proxy maintainer status
                proxied, devs, proxies = [], [], []
                proxy_map = {"yes": proxied, "no": devs, "proxy": proxies}
                for m in pkg.maintainers:
                    proxy_map[self._maintainer_proxied_key(m)].append(m)

                # check proxy maintainers
                if not devs and not proxies:
                    maintainers = sorted(map(str, pkg.maintainers))
                    yield MaintainerWithoutProxy(os.path.basename(loc), maintainers, pkg=pkg)
                elif not proxied and proxies:
                    yield ProxyWithoutProxied(os.path.basename(loc), pkg=pkg)
            elif not maintainer_needed:
                # check for missing maintainer-needed comment
                yield MaintainerNeeded(os.path.basename(loc), maintainer_needed, pkg=pkg)

            # check maintainer validity
            if projects := set(pkg.repo.projects_xml.projects):
                nonexistent = []
                wrong_maintainers = []
                for m in pkg.maintainers:
                    if m.maint_type == "project" and m.email not in projects:
                        nonexistent.append(m.email)
                    elif m.maint_type == "person" and m.email in projects:
                        wrong_maintainers.append(m.email)
                if nonexistent:
                    yield NonexistentProjectMaintainer(
                        os.path.basename(loc), sorted(nonexistent), pkg=pkg
                    )
                if wrong_maintainers:
                    yield WrongMaintainerType(
                        os.path.basename(loc), sorted(wrong_maintainers), pkg=pkg
                    )

    def _check_longdescription(self, pkg, loc, doc):
        if pkg.longdescription is not None:
            match_ratio = SequenceMatcher(None, pkg.description, pkg.longdescription).ratio()
            if match_ratio > 0.75:
                msg = "metadata.xml longdescription closely matches DESCRIPTION"
                yield RedundantLongDescription(msg, pkg=pkg)
            elif len(pkg.longdescription) < 80:
                msg = "metadata.xml longdescription is too short"
                yield RedundantLongDescription(msg, pkg=pkg)

    def _check_restricts(self, pkg, loc, doc):
        restricts = (
            c.get("restrict")
            for path in ("maintainer", "use/flag")
            for c in doc.xpath(f"/pkgmetadata/{path}[string(@restrict)]")
        )
        for restrict_str in restricts:
            try:
                restrict = atom(restrict_str, eapi="0")
                if restrict.key != pkg.key:
                    yield InvalidMetadataRestrict(
                        restrict_str, "references another package", pkg=pkg
                    )
                if restrict.use:
                    yield InvalidMetadataRestrict(
                        restrict_str, "USE-conditionals are prohibited", pkg=pkg
                    )
            except MalformedAtom as exc:
                yield InvalidMetadataRestrict(restrict_str, exc, pkg=pkg)

    def _check_remote_id(self, pkg, loc, doc):
        for u in pkg.upstreams:
            # empty values are already reported as PkgMetadataXmlEmptyElement
            if not u.name:
                continue
            try:
                validator, expected = self.remote_id_validators[u.type]
            except KeyError:  # pragma: no cover
                continue
            if not validator.match(u.name):
                yield InvalidRemoteID(u.type, u.name, expected, pkg=pkg)

    def _get_xml_location(self, pkg):
        """Return the metadata.xml location for a given package."""
        return pjoin(os.path.dirname(pkg.ebuild.path), "metadata.xml")


class CategoryMetadataXmlCheck(_XmlBaseCheck):
    """Category level metadata.xml scans."""

    _source = (sources.CategoryRepoSource, (), (("source", sources.RawRepoSource),))
    misformed_error = CatBadlyFormedXml
    invalid_error = CatInvalidXml
    missing_error = CatMissingMetadataXml
    catref_error = CatMetadataXmlInvalidCatRef
    pkgref_error = CatMetadataXmlInvalidPkgRef
    indent_error = CatMetadataXmlIndentation
    empty_element = CatMetadataXmlEmptyElement

    known_results = frozenset(
        [
            CatBadlyFormedXml,
            CatInvalidXml,
            CatMissingMetadataXml,
            CatMetadataXmlInvalidPkgRef,
            CatMetadataXmlInvalidCatRef,
            CatMetadataXmlIndentation,
            CatMetadataXmlEmptyElement,
        ]
    )

    def _get_xml_location(self, pkg):
        """Return the metadata.xml location for a given package's category."""
        return pjoin(self.repo_base, pkg.category, "metadata.xml")


class MissingRemoteId(results.PackageResult, results.Info):
    """Missing remote-id which was inferred from ebuilds.

    Based on URIs found in SRC_URI and HOMEPAGE, a remote-id can be suggested.
    If a remote-id of same type is already defined in ``metadata.xml``, the
    suggestion won't be reported. It ignores URIs ending with ``.diff`` or
    ``.patch``, as they might point to a fork or developer's space. It also
    ignores URIs that are conditional on USE flags.
    """

    def __init__(self, remote_type: str, value: str, uri: str, **kwarg):
        super().__init__(**kwarg)
        self.remote_type = remote_type
        self.value = value
        self.uri = uri

    @property
    def desc(self):
        return (
            f'missing <remote-id type="{self.remote_type}">'
            f"{self.value}</remote-id> (inferred from URI {self.uri!r})"
        )


class MissingRemoteIdCheck(Check):
    """Detect missing remote-ids based on SRC_URI and HOMEPAGE."""

    _source = sources.PackageRepoSource
    known_results = frozenset([MissingRemoteId])

    # Exclude api groups and raw project names to conform with https://docs.gitlab.com/ee/user/reserved_names.html
    # with the URI's which are most likely to end up in SRC_URI
    _gitlab_match = r"(?P<value>((?!api/)\w[^/]*/)+(?!raw/)\w[^/]*)"

    remotes_map = (
        ("bitbucket", r"https://bitbucket.org/(?P<value>[^/]+/[^/]+)"),
        ("codeberg", r"https://codeberg.org/(?P<value>[^/]+/[^/]+)"),
        ("freedesktop-gitlab", rf"https://gitlab.freedesktop.org/{_gitlab_match}"),
        ("github", r"https://github.com/(?P<value>[^/]+/[^/]+)"),
        ("gitlab", rf"https://gitlab.com/{_gitlab_match}"),
        ("gnome-gitlab", rf"https://gitlab.gnome.org/{_gitlab_match}"),
        ("heptapod", rf"https://foss.heptapod.net/{_gitlab_match}"),
        ("kde-invent", rf"https://invent.kde.org/{_gitlab_match}"),
        ("launchpad", r"https://launchpad.net/(?P<value>[^/]+)"),
        ("pypi", r"https://pypi.org/project/(?P<value>[^/]+)"),
        ("pypi", r"https://files.pythonhosted.org/packages/source/\S/(?P<value>[^/]+)"),
        ("savannah", r"https://savannah.gnu.org/projects/(?P<value>[^/]+)"),
        ("savannah-nongnu", r"https://savannah.nongnu.org/projects/(?P<value>[^/]+)"),
        ("sourceforge", r"https://downloads.sourceforge.(net|io)/(?:project/)?(?P<value>[^/]+)"),
        ("sourceforge", r"https://sourceforge.(net|io)/projects/(?P<value>[^/]+)"),
        ("sourceforge", r"https://(?P<value>[^/]+).sourceforge.(net|io)/"),
        ("sourcehut", r"https://sr.ht/(?P<value>[^/]+/[^/]+)"),
    )

    def __init__(self, options, **kwargs):
        super().__init__(options, **kwargs)
        self.remotes_map = tuple(
            (remote_type, re.compile(regex)) for remote_type, regex in self.remotes_map
        )

    @staticmethod
    def __filter_url(url: str) -> bool:
        if url.endswith((".patch", ".diff")):
            return False
        if "-crates.tar" in url:
            return False
        if "-deps.tar" in url:
            return False
        return True

    def feed(self, pkgset):
        remotes = {u.type: (None, None) for u in pkgset[0].upstreams}
        for pkg in sorted(pkgset, reverse=True):
            fetchables = iflatten_instance(
                pkg.generate_fetchables(
                    allow_missing_checksums=True,
                    ignore_unknown_mirrors=True,
                    skip_default_mirrors=True,
                ),
                (fetchable, Conditional),
            )
            all_urls: set[str] = set(
                chain.from_iterable(f.uri for f in fetchables if isinstance(f, fetchable))
            )
            urls = set(filter(self.__filter_url, all_urls))
            urls = sorted(urls.union(pkg.homepage), key=len)

            for remote_type, regex in self.remotes_map:
                if remote_type in remotes:
                    continue
                for url in urls:
                    if mo := regex.match(url):
                        remotes[remote_type] = (mo.group("value"), url)
                        break

        for remote_type, (value, url) in remotes.items():
            if value is not None:
                yield MissingRemoteId(remote_type, value, url, pkg=pkgset[0])
