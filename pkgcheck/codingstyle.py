# Copyright: 2007 Markus Ullmann <jokey@gentoo.org>
# License: BSD/GPL2

"""check for some bad coding styles like insinto's, old variables etc"""

from snakeoil.demandload import demandload

from pkgcheck import base

demandload("re")


class BadInsIntoDir(base.Result):

    """ebuild uses insinto where compact commands exist"""

    threshold = base.versioned_feed

    __slots__ = ("category", "package", "version", "line", "insintodir")

    def __init__(self, pkg, insintodir, line):
        base.Result.__init__(self)
        self._store_cpv(pkg)
        self.line = line
        self.insintodir = insintodir

    @property
    def short_desc(self):
        return "ebuild uses insinto %s on line %s" % (self.insintodir, self.line)


class BadInsIntoCheck(base.Template):

    """checking ebuild for bad insinto usage"""

    feed_type = base.ebuild_feed
    _bad_insinto = None
    _bad_etc = ("conf", "env", "init", "pam")
    _bad_cron = ("hourly", "daily", "weekly", "d")
    _bad_paths = ("/usr/share/applications",)

    known_results = (BadInsIntoDir,)

    def __init__(self, *args, **kwds):
        base.Template.__init__(self, *args, **kwds)
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
