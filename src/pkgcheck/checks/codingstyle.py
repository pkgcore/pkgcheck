"""check for some bad coding styles like insinto's, old variables etc"""

import re
from collections import defaultdict

from pkgcore.ebuild.eapi import EAPI
from snakeoil.demandload import demand_compile_regexp
from snakeoil.klass import jit_attr
from snakeoil.mappings import ImmutableDict
from snakeoil.strings import pluralism as _pl

from .. import results, sources
from . import Check, GentooRepoCheck

demand_compile_regexp(
    'ebuild_copyright_regex',
    r'^# Copyright (?P<begin>\d{4}-)?(?P<end>\d{4}) (?P<holder>.+)$')


class _CommandResult(results.VersionedResult):
    """Generic command result."""

    def __init__(self, command, line, lineno, **kwargs):
        super().__init__(**kwargs)
        self.command = command
        self.line = line
        self.lineno = lineno

    @property
    def usage_desc(self):
        return f'{self.command!r}'

    @property
    def desc(self):
        s = f'{self.usage_desc}, used on line {self.lineno}'
        if self.line != self.command:
            s += f': {self.line!r}'
        return s


class _EapiCommandResult(_CommandResult):
    """Generic EAPI command result."""

    _status = None

    def __init__(self, *args, eapi, **kwargs):
        super().__init__(*args, **kwargs)
        self.eapi = eapi

    @property
    def usage_desc(self):
        return f'{self.command!r} {self._status} in EAPI {self.eapi}'


class DeprecatedEapiCommand(_EapiCommandResult, results.Warning):
    """Ebuild uses a deprecated EAPI command."""

    _status = 'deprecated'


class BannedEapiCommand(_EapiCommandResult, results.Error):
    """Ebuild uses a banned EAPI command."""

    _status = 'banned'


class BadCommandsCheck(Check):
    """Scan ebuild for various deprecated and banned command usage."""

    _source = sources.EbuildFileRepoSource
    known_results = frozenset([DeprecatedEapiCommand, BannedEapiCommand])

    CMD_USAGE_REGEX = r'^(\s*|.*[|&{{(]+\s*)\b(?P<cmd>{})(?!\.)\b'

    def _cmds_regex(self, cmds):
        return re.compile(self.CMD_USAGE_REGEX.format(r'|'.join(cmds)))

    @jit_attr
    def regexes(self):
        d = {}
        for eapi_str, eapi in EAPI.known_eapis.items():
            regexes = []
            if eapi.bash_cmds_banned:
                regexes.append((
                    self._cmds_regex(eapi.bash_cmds_banned),
                    BannedEapiCommand,
                    {'eapi': eapi_str},
                ))
            if eapi.bash_cmds_deprecated:
                regexes.append((
                    self._cmds_regex(eapi.bash_cmds_deprecated),
                    DeprecatedEapiCommand,
                    {'eapi': eapi_str},
                ))
            d[eapi_str] = tuple(regexes)
        return ImmutableDict(d)

    def feed(self, pkg):
        regexes = self.regexes[str(pkg.eapi)]
        for lineno, line in enumerate(pkg.lines, 1):
            line = line.strip()
            if not line:
                continue
            if line[0] != '#':
                for regex, result_cls, kwargs in regexes:
                    match = regex.match(line)
                    if match is not None:
                        yield result_cls(match.group('cmd'), line, lineno, pkg=pkg, **kwargs)


class MissingSlash(results.VersionedResult, results.Error):
    """Ebuild uses a path variable missing a trailing slash."""

    def __init__(self, match, lines, **kwargs):
        super().__init__(**kwargs)
        self.match = match
        self.lines = tuple(lines)

    @property
    def desc(self):
        lines = ', '.join(map(str, self.lines))
        return f"{self.match} missing trailing slash on line{_pl(self.lines)}: {lines}"


class UnnecessarySlashStrip(results.VersionedResult, results.Warning):
    """Ebuild uses a path variable that strips a nonexistent slash."""

    def __init__(self, match, lines, **kwargs):
        super().__init__(**kwargs)
        self.match = match
        self.lines = tuple(lines)

    @property
    def desc(self):
        lines = ', '.join(map(str, self.lines))
        return f"{self.match} unnecessary slash strip on line{_pl(self.lines)}: {lines}"


class DoublePrefixInPath(results.VersionedResult, results.Error):
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


class PathVariablesCheck(Check):
    """Scan ebuild for path variables with various issues."""

    _source = sources.EbuildFileRepoSource
    known_results = frozenset([MissingSlash, UnnecessarySlashStrip, DoublePrefixInPath])
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

    def __init__(self, *args):
        super().__init__(*args)
        self.missing_regex = re.compile(r'(\${(%s)})"?\w+/' % r'|'.join(self.variables))
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

    def feed(self, pkg):
        missing = defaultdict(list)
        unnecessary = defaultdict(list)
        double_prefix = defaultdict(list)

        for lineno, line in enumerate(pkg.lines, 1):
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


class AbsoluteSymlink(results.VersionedResult, results.Warning):
    """Ebuild uses dosym with absolute paths instead of relative."""

    def __init__(self, abspath, line, **kwargs):
        super().__init__(**kwargs)
        self.abspath = abspath
        self.line = line

    @property
    def desc(self):
        return f"'dosym {self.abspath} ...' uses absolute path on line {self.line}"


class AbsoluteSymlinkCheck(Check):
    """Scan ebuild for dosym absolute path usage instead of relative."""

    _source = sources.EbuildFileRepoSource
    known_results = frozenset([AbsoluteSymlink])

    DIRS = ('bin', 'etc', 'lib', 'opt', 'sbin', 'srv', 'usr', 'var')

    def __init__(self, *args):
        super().__init__(*args)
        self.regex = re.compile(
            r'^\s*dosym\s+((["\'])?/(%s)(?(2).*?\2|\S*))' % r'|'.join(self.DIRS))

    def feed(self, pkg):
        for lineno, line in enumerate(pkg.lines, 1):
            if not line.strip():
                continue
            matches = self.regex.match(line)
            if matches is not None:
                yield AbsoluteSymlink(matches.groups()[0], lineno, pkg=pkg)


class BadInsIntoDir(results.VersionedResult, results.Warning):
    """Ebuild uses insinto where more compact commands exist."""

    def __init__(self, line, lineno, **kwargs):
        super().__init__(**kwargs)
        self.line = line
        self.lineno = lineno

    @property
    def desc(self):
        return f"bad insinto usage, line {self.lineno}: {self.line}"


class BadInsIntoCheck(Check):
    """Scan ebuild for bad insinto usage."""

    _source = sources.EbuildFileRepoSource
    _bad_insinto = None

    known_results = frozenset([BadInsIntoDir])

    def __init__(self, *args):
        super().__init__(*args)
        if self._bad_insinto is None:
            self._load_class_regex()

    @classmethod
    def _load_class_regex(cls):
        bad_etc = ("conf", "env", "init", "pam")
        bad_paths = ("/usr/share/applications",)

        patterns = []
        patterns.append("etc/(?:%s).d(?!/\w+)" % "|".join(bad_etc))
        patterns.extend(x.strip("/") for x in bad_paths)
        s = "|".join(patterns)
        s = s.replace("/", "/+")
        cls._bad_insinto = re.compile(rf'(?P<insinto>insinto[ \t]+/+(?:{s}))(?:$|[/ \t])')
        cls._bad_insinto_doc = re.compile(
            r'(?P<insinto>insinto[ \t]+/usr/share/doc/\$\{PF?\}(/\w+)*)(?:$|[/ \t])')

    def feed(self, pkg):
        for lineno, line in enumerate(pkg.lines, 1):
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


class ObsoleteUri(results.VersionedResult, results.Warning):
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


class ObsoleteUriCheck(Check):
    """Scan ebuild for obsolete URIs."""

    _source = sources.EbuildFileRepoSource
    known_results = frozenset([ObsoleteUri])

    REGEXPS = (
        (r'.*\b(?P<uri>(?P<prefix>https?://github\.com/.*?/.*?/)'
         r'(?:tar|zip)ball(?P<ref>\S*))',
         r'\g<prefix>archive\g<ref>.tar.gz'),
        (r'.*\b(?P<uri>(?P<prefix>https?://gitlab\.com/.*?/(?P<pkg>.*?)/)'
         r'repository/archive\.(?P<format>tar|tar\.gz|tar\.bz2|zip)'
         r'\?ref=(?P<ref>\S*))',
         r'\g<prefix>-/archive/\g<ref>/\g<pkg>-\g<ref>.\g<format>'),
    )

    def __init__(self, *args):
        super().__init__(*args)
        self.regexes = []
        for regexp, repl in self.REGEXPS:
            self.regexes.append((re.compile(regexp), repl))

    def feed(self, pkg):
        for lineno, line in enumerate(pkg.lines, 1):
            if not line.strip() or line.startswith('#'):
                continue
            # searching for multiple matches on a single line is too slow
            for regexp, repl in self.regexes:
                matches = regexp.match(line)
                if matches is not None:
                    uri = matches.group('uri')
                    yield ObsoleteUri(lineno, uri, regexp.sub(repl, uri), pkg=pkg)


class _EbuildHeaderResult(results.VersionedResult):
    """Generic ebuild header result."""

    def __init__(self, line, **kwargs):
        super().__init__(**kwargs)
        self.line = line


class InvalidCopyright(_EbuildHeaderResult, results.Error):
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


class OldGentooCopyright(_EbuildHeaderResult, results.Warning):
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


class NonGentooAuthorsCopyright(_EbuildHeaderResult, results.Error):
    """Ebuild with copyright stating owner other than "Gentoo Authors".

    The ebuild specifies explicit copyright owner, while the Gentoo repository
    policy specifies that all ebuilds must use "Gentoo Authors". If the owner
    is not listed in metadata/AUTHORS, addition can be requested via
    bugs.gentoo.org.
    """

    @property
    def desc(self):
        return f'copyright line must state "Gentoo Authors": {self.line!r}'


class InvalidLicenseHeader(_EbuildHeaderResult, results.Error):
    """Ebuild with invalid license header.

    The ebuild does not have with a valid license header.

    Ebuilds in the Gentoo repository must use:

        # Distributed under the terms of the GNU General Public License v2
    """

    @property
    def desc(self):
        return f'invalid license header: {self.line!r}'


class EbuildHeaderCheck(GentooRepoCheck):
    """Scan ebuild for incorrect copyright/license headers."""

    _source = sources.EbuildFileRepoSource
    known_results = frozenset([
        InvalidCopyright, OldGentooCopyright, NonGentooAuthorsCopyright,
        InvalidLicenseHeader,
    ])

    license_header = '# Distributed under the terms of the GNU General Public License v2'

    def feed(self, pkg):
        if pkg.lines:
            line = pkg.lines[0].strip()
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
                line = pkg.lines[1].strip('\n')
            except IndexError:
                line = ''
            if line != self.license_header:
                yield InvalidLicenseHeader(line, pkg=pkg)


class HomepageInSrcUri(results.VersionedResult, results.Warning):
    """${HOMEPAGE} is referenced in SRC_URI.

    SRC_URI is built on top of ${HOMEPAGE}. This is discouraged since HOMEPAGE
    is multi-valued by design, and is subject to potential changes that should
    not accidentally affect SRC_URI.
    """

    @property
    def desc(self):
        return '${HOMEPAGE} in SRC_URI'


class StaticSrcUri(results.VersionedResult, results.Warning):
    """SRC_URI contains static value instead of the dynamic equivalent."""

    def __init__(self, static_str, **kwargs):
        super().__init__(**kwargs)
        self.static_str = static_str

    @property
    def desc(self):
        return f'{self.static_str!r} in SRC_URI'


class RawSrcUriCheck(Check):
    """Scan raw SRC_URI content for various issues."""

    _source = sources.EbuildFileRepoSource
    known_results = frozenset([HomepageInSrcUri, StaticSrcUri])

    def __init__(self, *args):
        super().__init__(*args)
        self.src_uri_regex = re.compile(r'^\s*SRC_URI="[^"]*"', re.MULTILINE)

    def feed(self, pkg):
        src_uri = self.src_uri_regex.search(''.join(pkg.lines))
        if src_uri is not None:
            raw_src_uri = src_uri.group(0)
            if '${HOMEPAGE}' in raw_src_uri:
                yield HomepageInSrcUri(pkg=pkg)

            exts = pkg.eapi.archive_exts_regex_pattern
            P = re.escape(pkg.P)
            PV = re.escape(pkg.PV)
            static_src_uri_re = rf'/(?P<static_str>({P}{exts}(?="|\n)|{PV}(?=/)))'
            for match in re.finditer(static_src_uri_re, raw_src_uri):
                static_str = match.group('static_str')
                yield StaticSrcUri(static_str, pkg=pkg)
