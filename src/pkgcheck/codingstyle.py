"""check for some bad coding styles like insinto's, old variables etc"""

from collections import defaultdict

from snakeoil.demandload import demandload
from snakeoil.strings import pluralism

from . import base

demandload("re")


class HttpsAvailable(base.Warning):
    """Ebuild contains a http:// link that should use https:// instead."""

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
            self.link, pluralism(self.lines), ', '.join(map(str, self.lines)))


class HttpsAvailableCheck(base.Template):
    """Scan ebuild for http:// links that should use https://."""

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

    def feed(self, entry, reporter):
        pkg, lines = entry
        links = defaultdict(list)

        for lineno, line in enumerate(lines):
            if not line:
                continue
            # searching for multiple matches on a single line is too slow
            matches = self.regex.match(line)
            if matches is not None:
                links[matches.group(1)].append(lineno + 1)

        for link, lines in links.items():
            reporter.add_report(HttpsAvailable(pkg, link, lines))


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

    def feed(self, entry, reporter):
        pkg, lines = entry
        for lineno, line in enumerate(lines):
            if not line:
                continue
            # searching for multiple matches on a single line is too slow
            matches = self.regex.match(line)
            if matches is not None:
                reporter.add_report(PortageInternals(pkg, matches.group(2), lineno + 1))


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

    def feed(self, entry, reporter):
        pkg, lines = entry
        for lineno, line in enumerate(lines):
            if not line:
                continue
            matches = self.regex.match(line)
            if matches is not None:
                reporter.add_report(
                    AbsoluteSymlink(pkg, matches.groups()[0], lineno + 1))


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

    def feed(self, entry, reporter):
        pkg, lines = entry

        badf = self._bad_insinto.search
        for lineno, line in enumerate(lines):
            if not line:
                continue
            matches = badf(line)
            if matches is not None:
                reporter.add_report(
                    BadInsIntoDir(pkg, matches.groups()[0], lineno + 1))
