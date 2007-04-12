# Copyright: 2007 Markus Ullmann <jokey@gentoo.org>
# License: GPL2

"""check for some bad coding styles like insinto's, old variables etc"""

from pkgcore_checks import base

class BadInsIntoDotDir(base.Result):

    """ebuild uses insinto (conf|init|env).d"""

    threshold = base.versioned_feed

    __slots__ = ("category", "package", "version", "line", "dotdir")

    def __init__(self, pkg, dotdir, line):
        base.Result.__init__(self)
        self._store_cpv(pkg)
        self.line = line
        self.dotdir = dotdir

    @property
    def short_desc(self):
        return "ebuild uses insinto /etc/%s.d on line %s" % (self.dotdir,
	    self.line)


class BadInsIntoDotDirCheck(base.Template):

    """checking ebuild for bad insinto (conf|env|init).d usage"""

    feed_type = base.ebuild_feed

    known_results = (BadInsIntoDotDir,)

    def feed(self, entry, reporter):
        pkg, lines = entry

        for lineno, line in enumerate(lines):
            if line != '\n':
                for dotdir in ("conf", "env", "init"):
                    if line.find("insinto /etc/%s.d" % dotdir) >= 0:
                        reporter.add_report(
                            BadInsIntoDotDir(pkg, dotdir, lineno + 1))
                        break
