"""check for some bad coding styles like insinto's, old variables etc"""

import re
from collections import defaultdict

from snakeoil.demandload import demand_compile_regexp
from snakeoil.strings import pluralism as _pl

from .. import base

demand_compile_regexp(
    'ebuild_copyright_regex',
    r'^# Copyright (?P<begin>\d{4}-)?(?P<end>\d{4}) (?P<holder>.+)$')


class HttpsAvailable(base.VersionedResult, base.Warning):
    """Ebuild contains an ``http://`` link that should use ``https://`` instead."""

    def __init__(self, link, lines, **kwargs):
        super().__init__(**kwargs)
        self.link = link
        self.lines = tuple(lines)

    @property
    def desc(self):
        return (
            f"{self.link!r} should use https:// on line{_pl(self.lines)}: "
            f"{', '.join(map(str, self.lines))}"
        )


class HttpsAvailableCheck(base.Check):
    """Scan ebuild for ``http://`` links that should use ``https://``."""

    feed_type = base.ebuild_feed
    known_results = (HttpsAvailable,)

    SITES = (
        '([-._a-zA-Z0-9]*\\.)?apache\\.org',
        '(www\\.)?crosswire.org',
        '(www\\.)?ctan\\.org',
        '((alioth|packages(\\.qa)?|people|www)\\.)?debian\\.org',
        # Most FDO sites support https, but not all (like tango).
        # List the most common ones here for now.
        '((anongit|bugs|cgit|dri|patchwork|people|specifications|www|xcb|xorg)\\.)?freedesktop\\.org',
        '((bugs|dev|wiki|www)\\.)?gentoo\\.org',
        '((wiki)\\.)?github\\.(io|com)',
        'savannah\\.(non)?gnu\\.org',
        '((gcc|www)\\.)?gnu\\.org',
        '((archives|code|hackage|projects|wiki|www)\\.)?haskell\\.org',
        'curl\\.haxx\\.se',
        'invisible-island\\.net',
        '((bugzilla|git|mirrors|patchwork|planet|www(\\.wiki)?)\\.)?kernel\\.org',
        '((bugs|wiki|www)\\.)?linuxfoundation\\.org',
        '((download|hg)\\.)?netbeans\\.org',
        '(((download\\.)?pear|pecl|www)\\.)?php\\.net',
        '((docs|pypi|www)\\.)?python\\.org',
        '([-._a-zA-Z0-9]*\\.)?readthedocs\\.(io|org)',
        'rubygems\\.org',
        '(sf|sourceforge)\\.net',
        '(www\\.)?(enlightenment|sourceware|x)\\.org',
    )

    def __init__(self, options):
        super().__init__(options)
        # anchor the end of the URL so we don't get false positives,
        # e.g. http://github.com.foo.bar.com/
        self.regex = re.compile(r'.*(?P<uri>\bhttp://(%s)(\s|["\'/]|$))' % r'|'.join(self.SITES))

    def feed(self, entry):
        pkg, lines = entry
        links = defaultdict(list)

        for lineno, line in enumerate(lines, 1):
            if not line.strip():
                continue
            # searching for multiple matches on a single line is too slow
            matches = self.regex.match(line)
            if matches is not None:
                links[matches.group('uri')].append(lineno)

        for link, lines in links.items():
            yield HttpsAvailable(link, lines, pkg=pkg)


class PortageInternals(base.VersionedResult, base.Warning):
    """Ebuild uses a function or variable internal to portage."""

    def __init__(self, internal, line, **kwargs):
        super().__init__(**kwargs)
        self.internal = internal
        self.line = line

    @property
    def desc(self):
        return f"{self.internal!r} used on line {self.line}"


class PortageInternalsCheck(base.Check):
    """Scan ebuild for portage internals usage."""

    feed_type = base.ebuild_feed
    known_results = (PortageInternals,)

    INTERNALS = (
        'prepall',
        'prepalldocs',
        'prepallinfo',
        'prepallman',
        'prepallstrip',
        'prepinfo',
        'prepman',
        'prepstrip',
    )

    def __init__(self, options):
        super().__init__(options)
        self.regex = re.compile(
            r'^(\s*|.*[|&{(]+\s*)\b(?P<internal>%s)\b' % r'|'.join(self.INTERNALS))

    def feed(self, entry):
        pkg, lines = entry
        for lineno, line in enumerate(lines, 1):
            if not line.strip():
                continue
            # searching for multiple matches on a single line is too slow
            matches = self.regex.match(line)
            if matches is not None:
                yield PortageInternals(matches.group('internal'), lineno, pkg=pkg)


class MissingSlash(base.VersionedResult, base.Error):
    """Ebuild uses a path variable missing a trailing slash."""

    def __init__(self, match, lines, **kwargs):
        super().__init__(**kwargs)
        self.match = match
        self.lines = tuple(lines)

    @property
    def desc(self):
        lines = ', '.join(map(str, self.lines))
        return f"{self.match} missing trailing slash on line{_pl(self.lines)}: {lines}"


class UnnecessarySlashStrip(base.VersionedResult, base.Warning):
    """Ebuild uses a path variable that strips a nonexistent slash."""

    def __init__(self, match, lines, **kwargs):
        super().__init__(**kwargs)
        self.match = match
        self.lines = tuple(lines)

    @property
    def desc(self):
        lines = ', '.join(map(str, self.lines))
        return f"{self.match} unnecessary slash strip on line{_pl(self.lines)}: {lines}"


class DoublePrefixInPath(base.VersionedResult, base.Error):
    """Ebuild uses two consecutive paths including EPREFIX.

    Ebuild combines two path variables (or a variable and a getter), both
    of which include EPREFIX, resulting in double prefixing. This is the case
    when combining many pkg-config-based or alike getters with ED or EROOT.

    For example, ``${ED}$(python_get_sitedir)`` should be replaced
    with ``${D}$(python_get_sitedir)``.
    """

    def __init__(self, match, lines, **kwargs):
        super().__init__(**kwargs)
        self.match = match
        self.lines = tuple(lines)

    @property
    def desc(self):
        lines = ', '.join(map(str, self.lines))
        return (f"{self.match}: concatenates two paths containing EPREFIX "
                f"on line{_pl(self.lines)} {lines}")


class PathVariablesCheck(base.Check):
    """Scan ebuild for path variables with various issues."""

    feed_type = base.ebuild_feed
    known_results = (MissingSlash, UnnecessarySlashStrip, DoublePrefixInPath)
    prefixed_dir_functions = (
        'insinto', 'exeinto',
        'dodir', 'keepdir',
        'fowners', 'fperms',
        # java-pkg-2
        'java-pkg_jarinto', 'java-pkg_sointo',
        # python-utils-r1
        'python_scriptinto', 'python_moduleinto',
    )
    prefixed_variables = ('EROOT', 'ED')
    variables = ('ROOT', 'D') + prefixed_variables
    # TODO: add variables to mark this status in the eclasses in order to pull
    # this data from parsed eclass docs
    prefixed_getters = (
        # bash-completion-r1.eclass
        'get_bashcompdir', 'get_bashhelpersdir',
        # db-use.eclass
        'db_includedir',
        # golang-base.eclass
        'get_golibdir_gopath',
        # llvm.eclass
        'get_llvm_prefix',
        # python-utils-r1.eclass
        'python_get_sitedir', 'python_get_includedir',
        'python_get_library_path', 'python_get_scriptdir',
        # qmake-utils.eclass
        'qt4_get_bindir', 'qt5_get_bindir',
        # s6.eclass
        's6_get_servicedir',
        # systemd.eclass
        'systemd_get_systemunitdir', 'systemd_get_userunitdir',
        'systemd_get_utildir', 'systemd_get_systemgeneratordir',
    )
    prefixed_rhs_variables = (
        # catch silly ${ED}${EPREFIX} mistake ;-)
        'EPREFIX',
        # python-utils-r1.eclass
        'PYTHON', 'PYTHON_SITEDIR', 'PYTHON_INCLUDEDIR', 'PYTHON_LIBPATH',
        'PYTHON_CONFIG', 'PYTHON_SCRIPTDIR',
    )

    def __init__(self, options):
        super().__init__(options)
        self.missing_regex = re.compile(r'(\${(%s)})"?\w' % r'|'.join(self.variables))
        self.unnecessary_regex = re.compile(r'(\${(%s)%%/})' % r'|'.join(self.variables))
        self.double_prefix_regex = re.compile(
            r'(\${(%s)(%%/)?}/?\$(\((%s)\)|{(%s)}))' % (
                r'|'.join(self.prefixed_variables + ('EPREFIX',)),
                r'|'.join(self.prefixed_getters),
                r'|'.join(self.prefixed_rhs_variables)))
        self.double_prefix_func_regex = re.compile(
            r'\b(%s)\s[^&|;]*\$(\((%s)\)|{(%s)})' % (
                r'|'.join(self.prefixed_dir_functions),
                r'|'.join(self.prefixed_getters),
                r'|'.join(self.prefixed_rhs_variables)))
        # do not catch ${foo#${EPREFIX}} and similar
        self.double_prefix_func_false_positive_regex = re.compile(
            r'.*?[#]["]?\$(\((%s)\)|{(%s)})' % (
                r'|'.join(self.prefixed_getters),
                r'|'.join(self.prefixed_rhs_variables)))

    def feed(self, entry):
        pkg, lines = entry

        missing = defaultdict(list)
        unnecessary = defaultdict(list)
        double_prefix = defaultdict(list)

        for lineno, line in enumerate(lines, 1):
            line = line.strip()
            if not line:
                continue

            # flag double path prefix usage on uncommented lines only
            if line[0] != '#':
                match = self.double_prefix_regex.search(line)
                if match is not None:
                    double_prefix[match.group(1)].append(lineno)
                match = self.double_prefix_func_regex.search(line)
                if (match is not None and
                        self.double_prefix_func_false_positive_regex.match(
                            match.group(0)) is None):
                    double_prefix[match.group(0)].append(lineno)

            # skip EAPIs that don't require trailing slashes
            if pkg.eapi.options.trailing_slash:
                continue
            match = self.missing_regex.search(line)
            if match is not None:
                missing[match.group(1)].append(lineno)
            match = self.unnecessary_regex.search(line)
            if match is not None:
                unnecessary[match.group(1)].append(lineno)

        for match, lines in missing.items():
            yield MissingSlash(match, lines, pkg=pkg)
        for match, lines in unnecessary.items():
            yield UnnecessarySlashStrip(match, lines, pkg=pkg)
        for match, lines in double_prefix.items():
            yield DoublePrefixInPath(match, lines, pkg=pkg)


class AbsoluteSymlink(base.VersionedResult, base.Warning):
    """Ebuild uses dosym with absolute paths instead of relative."""

    def __init__(self, abspath, line, **kwargs):
        super().__init__(**kwargs)
        self.abspath = abspath
        self.line = line

    @property
    def desc(self):
        return f"'dosym {self.abspath} ...' uses absolute path on line {self.line}"


class AbsoluteSymlinkCheck(base.Check):
    """Scan ebuild for dosym absolute path usage instead of relative."""

    feed_type = base.ebuild_feed
    known_results = (AbsoluteSymlink,)

    DIRS = ('bin', 'etc', 'lib', 'opt', 'sbin', 'srv', 'usr', 'var')

    def __init__(self, options):
        super().__init__(options)
        self.regex = re.compile(
            r'^\s*dosym\s+((["\'])?/(%s)(?(2).*?\2|\S*))' % r'|'.join(self.DIRS))

    def feed(self, entry):
        pkg, lines = entry
        for lineno, line in enumerate(lines, 1):
            if not line.strip():
                continue
            matches = self.regex.match(line)
            if matches is not None:
                yield AbsoluteSymlink(matches.groups()[0], lineno, pkg=pkg)


class BadInsIntoDir(base.VersionedResult, base.Warning):
    """Ebuild uses insinto where more compact commands exist."""

    def __init__(self, line, lineno, **kwargs):
        super().__init__(**kwargs)
        self.line = line
        self.lineno = lineno

    @property
    def desc(self):
        return f"bad insinto usage, line {self.lineno}: {self.line}"


class BadInsIntoCheck(base.Check):
    """Scan ebuild for bad insinto usage."""

    feed_type = base.ebuild_feed
    _bad_insinto = None

    known_results = (BadInsIntoDir,)

    def __init__(self, options):
        super().__init__(options)
        if self._bad_insinto is None:
            self._load_class_regex()

    @classmethod
    def _load_class_regex(cls):
        bad_etc = ("conf", "env", "init", "pam")
        bad_paths = ("/usr/share/applications",)

        patterns = []
        patterns.append("etc/(?:%s).d" % "|".join(bad_etc))
        patterns.extend(x.strip("/") for x in bad_paths)
        s = "|".join(patterns)
        s = s.replace("/", "/+")
        cls._bad_insinto = re.compile(rf'(?P<insinto>insinto[ \t]+/+(?:{s}))(?:$|[/ \t])')
        cls._bad_insinto_doc = re.compile(
            r'(?P<insinto>insinto[ \t]+/usr/share/doc/\$\{PF?\}(/\w+)*)(?:$|[/ \t])')

    def feed(self, entry):
        pkg, lines = entry

        for lineno, line in enumerate(lines, 1):
            if not line.strip():
                continue
            matches = self._bad_insinto.search(line)
            if matches is not None:
                yield BadInsIntoDir(matches.group('insinto'), lineno, pkg=pkg)
                continue
            # Check for insinto usage that should be replaced with
            # docinto/dodoc [-r] under supported EAPIs.
            if pkg.eapi.options.dodoc_allow_recursive:
                matches = self._bad_insinto_doc.search(line)
                if matches is not None:
                    yield BadInsIntoDir(matches.group('insinto'), lineno, pkg=pkg)


class ObsoleteUri(base.VersionedResult, base.Warning):
    """URI used is obsolete.

    The URI used to fetch distfile is obsolete and can be replaced
    by something more modern. Note that the modern replacement usually
    results in different file contents, so you need to rename it (to
    avoid mirror collisions with the old file) and update the ebuild
    (for example, by removing no longer necessary vcs-snapshot.eclass).
    """

    def __init__(self, line, uri, replacement, **kwargs):
        super().__init__(**kwargs)
        self.line = line
        self.uri = uri
        self.replacement = replacement

    @property
    def desc(self):
        return (f"obsolete fetch URI: {self.uri} on line "
                f"{self.line}, should be replaced by: {self.replacement}")


class ObsoleteUriCheck(base.Check):
    """Scan ebuild for obsolete URIs."""

    feed_type = base.ebuild_feed
    known_results = (ObsoleteUri,)

    REGEXPS = (
        (r'.*\b(?P<uri>(?P<prefix>https?://github\.com/.*?/.*?/)'
         r'(?:tar|zip)ball(?P<ref>\S*))',
         r'\g<prefix>archive\g<ref>.tar.gz'),
        (r'.*\b(?P<uri>(?P<prefix>https?://gitlab\.com/.*?/(?P<pkg>.*?)/)'
         r'repository/archive\.(?P<format>tar|tar\.gz|tar\.bz2|zip)'
         r'\?ref=(?P<ref>\S*))',
         r'\g<prefix>-/archive/\g<ref>/\g<pkg>-\g<ref>.\g<format>'),
    )

    def __init__(self, options):
        super().__init__(options)
        self.regexes = []
        for regexp, repl in self.REGEXPS:
            self.regexes.append((re.compile(regexp), repl))

    def feed(self, entry):
        pkg, lines = entry

        for lineno, line in enumerate(lines, 1):
            if not line.strip() or line.startswith('#'):
                continue
            # searching for multiple matches on a single line is too slow
            for regexp, repl in self.regexes:
                matches = regexp.match(line)
                if matches is not None:
                    uri = matches.group('uri')
                    yield ObsoleteUri(lineno, uri, regexp.sub(repl, uri), pkg=pkg)


class _EbuildHeaderResult(base.VersionedResult, base.Warning):
    """Generic ebuild header result."""

    def __init__(self, line, **kwargs):
        super().__init__(**kwargs)
        self.line = line


class InvalidCopyright(_EbuildHeaderResult):
    """Ebuild with invalid copyright.

    The ebuild does not start with a valid copyright line. Each ebuild must
    start with a copyright line of the form:

        # Copyright YEARS MAIN-CONTRIBUTOR [OTHER-CONTRIBUTOR]... [and others]

    Ebuilds in the Gentoo repository must use:

        # Copyright YEARS Gentoo Authors
    """

    @property
    def desc(self):
        return f'invalid copyright: {self.line!r}'


class OldGentooCopyright(_EbuildHeaderResult):
    """Ebuild with old Gentoo Foundation copyright.

    The ebuild still assigns copyright to the Gentoo Foundation even though
    it has been committed after the new copyright policy was approved
    (2018-10-21).

    The ebuilds in Gentoo repository must use 'Gentoo Authors' instead. Ebuilds
    in other repositories may specify an explicit copyright holder instead.
    """

    @property
    def desc(self):
        return f'old copyright, update to "Gentoo Authors": {self.line!r}'


class NonGentooAuthorsCopyright(_EbuildHeaderResult):
    """Ebuild with copyright stating owner other than "Gentoo Authors".

    The ebuild specifies explicit copyright owner, while the Gentoo repository
    policy specifies that all ebuilds must use "Gentoo Authors". If the owner
    is not listed in metadata/AUTHORS, addition can be requested via
    bugs.gentoo.org.
    """

    @property
    def desc(self):
        return f'copyright line must state "Gentoo Authors": {self.line!r}'


class InvalidLicenseHeader(_EbuildHeaderResult):
    """Ebuild with invalid license header.

    The ebuild does not have with a valid license header.

    Ebuilds in the Gentoo repository must use:

        # Distributed under the terms of the GNU General Public License v2
    """

    @property
    def desc(self):
        return f'invalid license header: {self.line!r}'


class EbuildHeaderCheck(base.GentooRepoCheck):
    """Scan ebuild for incorrect copyright/license headers."""

    feed_type = base.ebuild_feed
    known_results = (
        InvalidCopyright, OldGentooCopyright, NonGentooAuthorsCopyright,
        InvalidLicenseHeader,
    )

    license_header = '# Distributed under the terms of the GNU General Public License v2'

    def feed(self, entry):
        pkg, lines = entry
        if lines:
            line = lines[0].strip()
            copyright = ebuild_copyright_regex.match(line)
            if copyright is None:
                yield InvalidCopyright(line, pkg=pkg)
            # Copyright policy is active since 2018-10-21, so it applies
            # to all ebuilds committed in 2019 and later
            elif int(copyright.group('end')) >= 2019:
                if copyright.group('holder') == 'Gentoo Foundation':
                    yield OldGentooCopyright(line, pkg=pkg)
                # Gentoo policy requires 'Gentoo Authors'
                elif copyright.group('holder') != 'Gentoo Authors':
                    yield NonGentooAuthorsCopyright(line, pkg=pkg)

            try:
                line = lines[1].strip('\n')
            except IndexError:
                line = ''
            if line != self.license_header:
                yield InvalidLicenseHeader(line, pkg=pkg)


class HomepageInSrcUri(base.VersionedResult, base.Warning):
    """${HOMEPAGE} is referenced in SRC_URI.

    SRC_URI is built on top of ${HOMEPAGE}. This is discouraged since HOMEPAGE
    is multi-valued by design, and is subject to potential changes that should
    not accidentally affect SRC_URI.
    """

    @property
    def desc(self):
        return "${HOMEPAGE} in SRC_URI"


class HomepageInSrcUriCheck(base.Check):
    """Scan ebuild for ${HOMEPAGE} in SRC_URI."""

    feed_type = base.ebuild_feed
    known_results = (HomepageInSrcUri,)

    def __init__(self, options):
        super().__init__(options)
        self.regex = re.compile(r'^\s*SRC_URI="[^"]*[$]{HOMEPAGE}', re.M|re.S)

    def feed(self, entry):
        pkg, lines = entry

        match = self.regex.search(''.join(lines))
        if match is not None:
            yield HomepageInSrcUri(pkg=pkg)
