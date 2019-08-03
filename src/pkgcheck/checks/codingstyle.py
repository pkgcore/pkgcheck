"""check for some bad coding styles like insinto's, old variables etc"""

from collections import defaultdict

from snakeoil.demandload import demandload
from snakeoil.strings import pluralism as _pl

from .. import base

demandload("re")


class HttpsAvailable(base.Warning):
    """Ebuild contains an ``http://`` link that should use ``https://`` instead."""

    __slots__ = ("category", "package", "version", "link", "lines")
    threshold = base.versioned_feed

    def __init__(self, pkg, link, lines):
        super().__init__()
        self._store_cpv(pkg)
        self.link = link
        self.lines = tuple(lines)

    @property
    def short_desc(self):
        return "'%s' link should use https:// on line%s: %s" % (
            self.link, _pl(self.lines), ', '.join(map(str, self.lines)))


class HttpsAvailableCheck(base.Template):
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
        self.regex = re.compile(r'.*(\bhttp://(%s)(\s|["\'/]|$))' % r'|'.join(self.SITES))

    def feed(self, entry):
        pkg, lines = entry
        links = defaultdict(list)

        for lineno, line in enumerate(lines, 1):
            if not line.strip():
                continue
            # searching for multiple matches on a single line is too slow
            matches = self.regex.match(line)
            if matches is not None:
                links[matches.group(1)].append(lineno)

        for link, lines in links.items():
            yield HttpsAvailable(pkg, link, lines)


class PortageInternals(base.Warning):
    """Ebuild uses a function or variable internal to portage."""

    __slots__ = ("category", "package", "version", "internal", "line")
    threshold = base.versioned_feed

    def __init__(self, pkg, internal, line):
        super().__init__()
        self._store_cpv(pkg)
        self.internal = internal
        self.line = line

    @property
    def short_desc(self):
        return f"{self.internal!r} used on line {self.line}"


class PortageInternalsCheck(base.Template):
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
        self.regex = re.compile(r'^(\s*|.*[|&{(]+\s*)\b(%s)\b' % r'|'.join(self.INTERNALS))

    def feed(self, entry):
        pkg, lines = entry
        for lineno, line in enumerate(lines, 1):
            if not line.strip():
                continue
            # searching for multiple matches on a single line is too slow
            matches = self.regex.match(line)
            if matches is not None:
                yield PortageInternals(pkg, matches.group(2), lineno)


class MissingSlash(base.Error):
    """Ebuild uses a path variable missing a trailing slash."""

    __slots__ = ("category", "package", "version", "variable", "lines")
    threshold = base.versioned_feed

    def __init__(self, pkg, variable, lines):
        super().__init__()
        self._store_cpv(pkg)
        self.variable = variable
        self.lines = tuple(lines)

    @property
    def short_desc(self):
        lines = ', '.join(map(str, self.lines))
        return f"{self.variable} missing trailing slash on line{_pl(self.lines)}: {lines}"


class UnnecessarySlashStrip(base.Warning):
    """Ebuild uses a path variable that strips a nonexistent slash."""

    __slots__ = ("category", "package", "version", "variable", "lines")
    threshold = base.versioned_feed

    def __init__(self, pkg, variable, lines):
        super().__init__()
        self._store_cpv(pkg)
        self.variable = variable
        self.lines = tuple(lines)

    @property
    def short_desc(self):
        lines = ', '.join(map(str, self.lines))
        return f"{self.variable} unnecessary slash strip on line{_pl(self.lines)}: {lines}"


class DoublePrefixInPath(base.Error):
    """Ebuild uses two consecutive paths including EPREFIX.

    Ebuild combines two path variables (or a variable and a getter), both
    of which include EPREFIX, resulting in double prefixing. This is the case
    when combining many pkg-config-based or alike getters with ED or EROOT.

    For example, ``${ED}$(python_get_sitedir)`` should be replaced
    with ``${D}$(python_get_sitedir)``.
    """

    __slots__ = ("category", "package", "version", "variable", "lines")
    threshold = base.versioned_feed

    def __init__(self, pkg, variable, lines):
        super().__init__()
        self._store_cpv(pkg)
        self.variable = variable
        self.lines = tuple(lines)

    @property
    def short_desc(self):
        lines = ', '.join(map(str, self.lines))
        return (f"{self.variable} concatenates two variables containing "
                f"EPREFIX on line{_pl(self.lines)}: {lines}")


class PathVariablesCheck(base.Template):
    """Scan ebuild for path variables with various issues."""

    feed_type = base.ebuild_feed
    known_results = (MissingSlash, UnnecessarySlashStrip, DoublePrefixInPath)
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

    def feed(self, entry):
        pkg, lines = entry

        missing = defaultdict(list)
        unnecessary = defaultdict(list)
        double_prefix = defaultdict(list)

        for lineno, line in enumerate(lines, 1):
            if not line.strip():
                continue

            match = self.double_prefix_regex.search(line)
            if match is not None:
                double_prefix[match.group(1)].append(lineno)

            # skip EAPIs that don't require trailing slashes
            if pkg.eapi.options.trailing_slash:
                continue
            match = self.missing_regex.search(line)
            if match is not None:
                missing[match.group(1)].append(lineno)
            match = self.unnecessary_regex.search(line)
            if match is not None:
                unnecessary[match.group(1)].append(lineno)

        for var, lines in missing.items():
            yield MissingSlash(pkg, var, lines)
        for var, lines in unnecessary.items():
            yield UnnecessarySlashStrip(pkg, var, lines)
        for var, lines in double_prefix.items():
            yield DoublePrefixInPath(pkg, var, lines)


class AbsoluteSymlink(base.Warning):
    """Ebuild uses dosym with absolute paths instead of relative."""

    threshold = base.versioned_feed

    __slots__ = ("category", "package", "version", "line", "abspath")

    def __init__(self, pkg, abspath, line):
        super().__init__()
        self._store_cpv(pkg)
        self.abspath = abspath
        self.line = line

    @property
    def short_desc(self):
        return f"'dosym {self.abspath} ...' uses absolute path on line {self.line}"


class AbsoluteSymlinkCheck(base.Template):
    """Scan ebuild for dosym absolute path usage instead of relative."""

    feed_type = base.ebuild_feed
    known_results = (AbsoluteSymlink,)

    DIRS = ('bin', 'etc', 'lib', 'opt', 'sbin', 'srv', 'usr', 'var')

    def __init__(self, options):
        super().__init__(options)
        self.regex = re.compile(r'^\s*dosym\s+["\']?(/(%s)\S*)' % r'|'.join(self.DIRS))

    def feed(self, entry):
        pkg, lines = entry
        for lineno, line in enumerate(lines, 1):
            if not line.strip():
                continue
            matches = self.regex.match(line)
            if matches is not None:
                yield AbsoluteSymlink(pkg, matches.groups()[0], lineno)


class BadInsIntoDir(base.Warning):
    """Ebuild uses insinto where more compact commands exist."""

    threshold = base.versioned_feed

    __slots__ = ("category", "package", "version", "line", "insintodir")

    def __init__(self, pkg, insintodir, line):
        super().__init__()
        self._store_cpv(pkg)
        self.line = line
        self.insintodir = insintodir

    @property
    def short_desc(self):
        return f"ebuild uses insinto {self.insintodir} on line {self.line}"


class BadInsIntoCheck(base.Template):
    """Scan ebuild for bad insinto usage."""

    feed_type = base.ebuild_feed
    _bad_insinto = None
    _bad_etc = ("conf", "env", "init", "pam")
    _bad_cron = ("hourly", "daily", "weekly", "d")
    _bad_paths = ("/usr/share/applications",)

    known_results = (BadInsIntoDir,)

    def __init__(self, options):
        super().__init__(options)
        if self._bad_insinto is None:
            self._load_class_regex()

    @classmethod
    def _load_class_regex(cls):
        patterns = []
        if cls._bad_etc:
            patterns.append("etc/(?:%s).d" % "|".join(cls._bad_etc))
        if cls._bad_cron:
            patterns.append("etc/cron.(?:%s)" % "|".join(cls._bad_cron))
        if cls._bad_paths:
            patterns.extend(x.strip("/") for x in cls._bad_paths)
        s = "|".join(patterns)
        s = s.replace("/", "/+")
        cls._bad_insinto = re.compile("insinto[ \t]+(/+(?:%s))(?:$|[/ \t])" % s)

    def feed(self, entry):
        pkg, lines = entry

        badf = self._bad_insinto.search
        for lineno, line in enumerate(lines, 1):
            if not line.strip():
                continue
            matches = badf(line)
            if matches is not None:
                yield BadInsIntoDir(pkg, matches.groups()[0], lineno)


class ObsoleteUri(base.Warning):
    """URI used is obsolete.

    The URI used to fetch distfile is obsolete and can be replaced
    by something more modern.
    """

    __slots__ = ("category", "package", "version", "line", "uri", "replacement")
    threshold = base.versioned_feed

    def __init__(self, pkg, line, uri, replacement):
        super().__init__()
        self._store_cpv(pkg)
        self.line = line
        self.uri = uri
        self.replacement = replacement

    @property
    def short_desc(self):
        return (f"obsolete fetch URI: {self.uri} on line "
                f"{self.line}, should be replaced by: {self.replacement}")


class ObsoleteUriCheck(base.Template):
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
        links = defaultdict(list)

        for lineno, line in enumerate(lines, 1):
            if not line.strip() or line.startswith('#'):
                continue
            # searching for multiple matches on a single line is too slow
            for regexp, repl in self.regexes:
                matches = regexp.match(line)
                if matches is not None:
                    uri = matches.group('uri')
                    yield ObsoleteUri(pkg, lineno, uri, regexp.sub(repl, uri))
