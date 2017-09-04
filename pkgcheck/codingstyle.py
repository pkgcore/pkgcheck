"""check for some bad coding styles like insinto's, old variables etc"""

from snakeoil.demandload import demandload, demand_compile_regexp

from pkgcheck import base

demandload("re")

demand_compile_regexp(
    'dosym_regexp',
    r'^\s*dosym\s+["\']?(/(bin|etc|lib|opt|sbin|srv|usr|var)\S*)')


class HttpsAvailable(base.Warning):
    """Ebuild contains a http:// link that should use https:// instead."""

    threshold = base.versioned_feed

    __slots__ = ("category", "package", "link", "line")

    def __init__(self, pkg, link, line):
        super(HttpsAvailable, self).__init__()
        self._store_cpv(pkg)
        self.link = link
        self.line = line

    @property
    def short_desc(self):
        return "'%s' link on line %s should use https://" % (self.link, self.line)


class HttpsAvailableCheck(base.Template):
    """Scan ebuild for http:// links that should use https://."""

    feed_type = base.ebuild_feed
    known_results = (HttpsAvailable,)

    SITES = (
        '([-._a-zA-Z0-9]*\.)?apache\.org',
        '((alioth|packages(\.qa)?|people|www)\.)?debian\.org',
        # Most FDO sites support https, but not all (like tango).
        # List the most common ones here for now.
        '((anongit|bugs|cgit|dri|patchwork|people|specifications|www|xcb|xorg)\.)?freedesktop\.org',
        '((bugs|dev|wiki|www)\.)?gentoo\.org',
        '((wiki)\.)?github\.(io|com)',
        'savannah\.(non)?gnu\.org',
        '((gcc|www)\.)?gnu\.org',
        'curl\.haxx\.se',
        '((bugzilla|git|mirrors|patchwork|planet|www(\.wiki)?)\.)?kernel\.org',
        '((bugs|wiki|www)\.)?linuxfoundation\.org',
        '((docs|pypi|www)\.)?python\.org',
        '(sf|sourceforge)\.net',
        '(www\.)?(enlightenment|sourceware|x)\.org',
    )

    # anchor the end of the URL so we don't get false positives,
    # e.g. http://github.com.foo.bar.com/
    demand_compile_regexp(
        'https_sites_regex',
        r'.*(\bhttp://(%s)(\s|["\'/]|$))' % r'|'.join(SITES))

    def __init__(self, options):
        super(HttpsAvailableCheck, self).__init__(options)

    def feed(self, entry, reporter):
        pkg, lines = entry
        for lineno, line in enumerate(lines):
            if not line:
                continue
            # searching for multiple matches on a single line is too slow
            matches = https_sites_regex.match(line)
            if matches is not None:
                reporter.add_report(HttpsAvailable(pkg, matches.group(1), lineno + 1))


class AbsoluteSymlink(base.Warning):
    """Ebuild uses dosym with absolute paths instead of relative."""

    threshold = base.versioned_feed

    __slots__ = ("category", "package", "version", "line", "abspath")

    def __init__(self, pkg, abspath, line):
        super(AbsoluteSymlink, self).__init__()
        self._store_cpv(pkg)
        self.abspath = abspath
        self.line = line

    @property
    def short_desc(self):
        return "'dosym %s ...' uses absolute path on line %s" % (self.abspath, self.line)


class AbsoluteSymlinkCheck(base.Template):
    """Scan ebuild for dosym absolute path usage instead of relative."""

    feed_type = base.ebuild_feed

    known_results = (AbsoluteSymlink,)

    def __init__(self, options):
        super(AbsoluteSymlinkCheck, self).__init__(options)

    def feed(self, entry, reporter):
        pkg, lines = entry
        for lineno, line in enumerate(lines):
            if not line:
                continue
            matches = dosym_regexp.match(line)
            if matches is not None:
                reporter.add_report(
                    AbsoluteSymlink(pkg, matches.groups()[0], lineno + 1))


class BadInsIntoDir(base.Warning):
    """Ebuild uses insinto where more compact commands exist."""

    threshold = base.versioned_feed

    __slots__ = ("category", "package", "version", "line", "insintodir")

    def __init__(self, pkg, insintodir, line):
        super(BadInsIntoDir, self).__init__()
        self._store_cpv(pkg)
        self.line = line
        self.insintodir = insintodir

    @property
    def short_desc(self):
        return "ebuild uses insinto %s on line %s" % (self.insintodir, self.line)


class BadInsIntoCheck(base.Template):
    """Scan ebuild for bad insinto usage."""

    feed_type = base.ebuild_feed
    _bad_insinto = None
    _bad_etc = ("conf", "env", "init", "pam")
    _bad_cron = ("hourly", "daily", "weekly", "d")
    _bad_paths = ("/usr/share/applications",)

    known_results = (BadInsIntoDir,)

    def __init__(self, options):
        super(BadInsIntoCheck, self).__init__(options)
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
