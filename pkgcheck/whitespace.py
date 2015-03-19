# Copyright: 2006 Markus Ullmann <jokey@gentoo.org>
# Copyright: 2006 Marien Zwart <marienz@gentoo.org>
# License: BSD/GPL2

from snakeoil.demandload import demand_compile_regexp

from pkgcheck import base

demand_compile_regexp('indent_regexp', '^\t* \t+')

class base_whitespace(base.Result):

    threshold = base.versioned_feed

    __slots__ = ()

    @property
    def lines_str(self):
        if len(self.lines) == 1:
            return "line %i" % self.lines[0]
        return "lines %s" % ', '.join(str(x) for x in self.lines)


class WhitespaceFound(base_whitespace):

    """leading or trailing whitespaces are found"""

    __slots__ = ("category", "package", "version", "lines", "leadtrail")

    def __init__(self, pkg, leadtrail, lines):
        base.Result.__init__(self)
        self._store_cpv(pkg)
        self.lines = lines
        self.leadtrail = leadtrail

    @property
    def short_desc(self):
        return "ebuild has %s whitespace on %s" % (
            self.leadtrail, self.lines_str)


class WrongIndentFound(base_whitespace):

    """leading or trailing whitespaces are found"""

    __slots__ = ("category", "package", "version", "lines")

    def __init__(self, pkg, lines):
        base.Result.__init__(self)
        self._store_cpv(pkg)
        self.lines = lines

    @property
    def short_desc(self):
        return "ebuild has whitespace in indentation on %s" % self.lines_str


class DoubleEmptyLine(base_whitespace):

    """unneeded blank lines are found"""

    __slots__ = ("category", "package", "version", "lines")

    def __init__(self, pkg, lines):
        base.Result.__init__(self)
        self._store_cpv(pkg)
        self.lines = lines

    @property
    def short_desc(self):
        return "ebuild has unneeded empty %s" % self.lines_str


class TrailingEmptyLine(base.Result):

    """unneeded blank lines are found"""

    __slots__ = ("category", "package", "version")

    threshold = base.versioned_feed

    def __init__(self, pkg):
        base.Result.__init__(self)
        self._store_cpv(pkg)

    short_desc = "ebuild has trailing blank line(s)"


class NoFinalNewline(base.Result):

    """Ebuild's last line does not have a final newline."""

    __slots__ = ("category", "package", "version")

    threshold = base.versioned_feed

    def __init__(self, pkg):
        base.Result.__init__(self)
        self._store_cpv(pkg)

    short_desc = "ebuild lacks an ending newline"


class WhitespaceCheck(base.Template):

    """checking ebuild for (useless) whitespaces"""

    feed_type = base.ebuild_feed
    known_results = (
        WhitespaceFound, WrongIndentFound, DoubleEmptyLine,
        TrailingEmptyLine, NoFinalNewline)

    def feed(self, entry, reporter):
        pkg, lines = entry
        lastlineempty = False
        trailing = []
        leading = []
        indent = []
        double_empty = []

        for lineno, line in enumerate(lines):
            if line != '\n':
                lastlineempty = False
                if line[-2:-1] == ' ' or line[-2:-1] == '\t':
                    trailing.append(lineno + 1)
                elif line[0] == ' ':
                    leading.append(lineno + 1)
                if indent_regexp.match(line):
                    indent.append(lineno + 1)
            elif lastlineempty:
                double_empty.append(lineno + 1)
            else:
                lastlineempty = True
        if trailing:
            reporter.add_report(
                WhitespaceFound(pkg, "trailing", trailing))
        if leading:
            reporter.add_report(
                WhitespaceFound(pkg, "leading", leading))
        if indent:
            reporter.add_report(WrongIndentFound(pkg, indent))
        if double_empty:
            reporter.add_report(DoubleEmptyLine(pkg, double_empty))
        if lastlineempty:
            reporter.add_report(TrailingEmptyLine(pkg))

        # Dealing with empty ebuilds is just paranoia
        if lines and not lines[-1].endswith('\n'):
            reporter.add_report(NoFinalNewline(pkg))
