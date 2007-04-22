# Copyright: 2007 Markus Ullmann <jokey@gentoo.org>
# License: GPL2

"""check for some bad coding styles like insinto's, old variables etc"""

from pkgcore_checks import base

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
        return "ebuild uses insinto %s on line %s" % (self.insintodir,
	    self.line)


class BadInsIntoCheck(base.Template):

    """checking ebuild for bad insinto usage"""

    feed_type = base.ebuild_feed

    known_results = (BadInsIntoDir,)

    def feed(self, entry, reporter):
        pkg, lines = entry

        for lineno, line in enumerate(lines):
            if line != '\n':
                if line.find("insinto"):
                    for dotdir in ("conf", "env", "init", "pam"):
                        if line.find("insinto /etc/%s.d" % dotdir) >= 0:
                            reporter.add_report(
                                BadInsIntoDir(pkg, "/etc/%s.d/" % dotdir,
                                    lineno + 1))
                            break
                    if line.find("insinto /usr/share/applications") >= 0:
                        reporter.add_report(
                            BadInsIntoDir(pkg, "/usr/share/applications",
                                lineno + 1))
