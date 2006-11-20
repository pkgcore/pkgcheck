# Copyright: 2006 Markus Ullmann <jokey@gentoo.org>
# License: GPL2

import os
from pkgcore_checks import base

class WhitespaceCheck(base.Template):

    """checking ebuild for (useless) whitespaces"""

    feed_type = base.ebuild_feed

    def feed(self, feed, reporter):
        for pkg, lines in feed:
            yield pkg, lines
            lastlineempty = False
            for lineno, line in enumerate(lines):
                if line != '\n':
                    lastlineempty = False
                    if line[-2:-1] == ' ' or line[-2:-1] == '\t':
                        reporter.add_report(
                            WhitespaceFound(pkg, lineno + 1, "trailing"))
                    elif line[0] == ' ':
                        reporter.add_report(
                            WhitespaceFound(pkg, lineno + 1, "leading"))
                else:
                    if lastlineempty:
                        reporter.add_report(DoubleEmptyLine(pkg, lineno + 1))
                    else:
                        lastlineempty = True


class WhitespaceFound(base.Result):

    """leading or trailing whitespaces are found"""

    __slots__ = ("category", "package", "filename")

    def __init__(self, pkg, linenumber, leadtrail):
        base.Result.__init__(self)
        self._store_cpv(pkg)
        self.linenumber = linenumber
        self.leadtrail = leadtrail

    def to_str(self):
        return "%s/%s-%s.ebuild has %s whitespace on line %s" % (
            self.category, self.package, self.version, self.leadtrail,
            self.linenumber)

    def to_xml(self):
        return """\
<check name="%s">
    <category>%s</category>
    <package>%s</package>
    <version>%s</version>
    <msg>ebuild has %s whitespace on line %s</msg>
</check>""" % (self.__class__.__name__, self.category, self.package,
               self.version, self.leadtrail, self.linenumber)


class DoubleEmptyLine(base.Result):

    """unneeded blank lines are found"""

    __slots__ = ("category", "package", "filename")

    def __init__(self, pkg, linenumber):
        base.Result.__init__(self)
        self._store_cpv(pkg)
        self.linenumber = linenumber

    def to_str(self):
        return "%s/%s-%s.ebuild has unneeded empty line %s" % (
            self.category, self.package, self.version, self.linenumber)

    def to_xml(self):
        return \
"""<check name="%s">
    <category>%s</category>
    <package>%s</package>
    <version>%s</version>
    <msg>ebuild has unneeded empty line %s</msg>
</check>""" % (self.__class__.__name__, self.category, self.package,
    self.version, self.linenumber)
