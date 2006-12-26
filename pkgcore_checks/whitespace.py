# Copyright: 2006 Markus Ullmann <jokey@gentoo.org>
# Copyright: 2006 Marien Zwart <marienz@gentoo.org>
# License: GPL2

import os
from pkgcore_checks import base

class WhitespaceCheck(base.Template):

    """checking ebuild for (useless) whitespaces"""

    feed_type = base.ebuild_feed

    def feed(self, entry, reporter):
        pkg, lines = entry
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
                if line.find("\t ") >= 0:
                    reporter.add_report(
                        WrongIndentFound(pkg, lineno +1))
            else:
                if lastlineempty:
                    reporter.add_report(DoubleEmptyLine(pkg, lineno + 1))
                else:
                    lastlineempty = True
        if lastlineempty:
            reporter.add_report(TrailingEmptyLine(pkg))
        # Dealing with empty ebuilds is just paranoia
        if lines and not lines[-1].endswith('\n'):
            reporter.add_report(NoFinalNewline(pkg))


class WhitespaceFound(base.Result):

    """leading or trailing whitespaces are found"""

    __slots__ = ("category", "package", "version", "linenumber", "leadtrail")

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

class WrongIndentFound(base.Result):

    """leading or trailing whitespaces are found"""

    __slots__ = ("category", "package", "version", "linenumber")

    def __init__(self, pkg, linenumber):
        base.Result.__init__(self)
        self._store_cpv(pkg)
        self.linenumber = linenumber

    def to_str(self):
        return "%s/%s-%s.ebuild has whitespace in indentation on line %s" % (
            self.category, self.package, self.version, self.linenumber)

    def to_xml(self):
        return """\
<check name="%s">
    <category>%s</category>
    <package>%s</package>
    <version>%s</version>
    <msg>ebuild has whitespace in indentation on line %s</msg>
</check>""" % (self.__class__.__name__, self.category, self.package,
               self.version, self.linenumber)


class DoubleEmptyLine(base.Result):

    """unneeded blank lines are found"""

    __slots__ = ("category", "package", "version", "linenumber")

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


class TrailingEmptyLine(base.Result):

    """unneeded blank lines are found"""

    __slots__ = ("category", "package", "version")

    def __init__(self, pkg):
        base.Result.__init__(self)
        self._store_cpv(pkg)

    def to_str(self):
        return "%s/%s-%s.ebuild has trailing blank line(s)" % (
            self.category, self.package, self.version)

    def to_xml(self):
        return \
"""<check name="%s">
    <category>%s</category>
    <package>%s</package>
    <version>%s</version>
    <msg>ebuild has trailing blank line(s)</msg>
</check>""" % (
            self.__class__.__name__, self.category, self.package, self.version)


class NoFinalNewline(base.Result):

    """Ebuild's last line does not have a final newline."""

    __slots__ = ("category", "package", "version")

    def __init__(self, pkg):
        base.Result.__init__(self)
        self._store_cpv(pkg)

    def to_str(self):
        return "%s/%s-%s.ebuild does not end in a newline" % (
            self.category, self.package, self.version)

    def to_xml(self):
        return \
"""<check name="%s">
    <category>%s</category>
    <package>%s</package>
    <version>%s</version>
    <msg>ebuild does not end in a newline</msg>
</check>""" % (
            self.__class__.__name__, self.category, self.package, self.version)
