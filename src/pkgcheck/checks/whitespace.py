from snakeoil.demandload import demand_compile_regexp
from snakeoil.strings import pluralism as _pl

from .. import results, sources
from . import Check

demand_compile_regexp('indent_regexp', '^\t* \t+')


class _Whitespace(results.VersionedResult, results.Warning):

    @property
    def lines_str(self):
        return f"line{_pl(self.lines)}: {', '.join(str(x) for x in self.lines)}"


class WhitespaceFound(_Whitespace):
    """Leading or trailing whitespace found."""

    def __init__(self, leadtrail, lines, **kwargs):
        super().__init__(**kwargs)
        self.lines = tuple(lines)
        self.leadtrail = leadtrail

    @property
    def desc(self):
        return f"ebuild has {self.leadtrail} whitespace on {self.lines_str}"


class WrongIndentFound(_Whitespace):
    """Incorrect indentation whitespace found."""

    def __init__(self, lines, **kwargs):
        super().__init__(**kwargs)
        self.lines = tuple(lines)

    @property
    def desc(self):
        return f"ebuild has whitespace in indentation on {self.lines_str}"


class DoubleEmptyLine(_Whitespace):
    """Unneeded blank lines found."""

    def __init__(self, lines, **kwargs):
        super().__init__(**kwargs)
        self.lines = tuple(lines)

    @property
    def desc(self):
        return f"ebuild has unneeded empty {self.lines_str}"


class TrailingEmptyLine(results.VersionedResult, results.Warning):
    """Unneeded trailing blank lines found."""

    desc = "ebuild has trailing blank line(s)"


class NoFinalNewline(results.VersionedResult, results.Warning):
    """Ebuild's last line does not have a final newline."""

    desc = "ebuild lacks an ending newline"


class WhitespaceCheck(Check):
    """Scan ebuild for useless whitespace."""

    _source = sources.EbuildFileRepoSource
    known_results = frozenset([
        WhitespaceFound, WrongIndentFound, DoubleEmptyLine,
        TrailingEmptyLine, NoFinalNewline,
    ])

    def feed(self, pkg):
        lastlineempty = False
        trailing = []
        leading = []
        indent = []
        double_empty = []

        for lineno, line in enumerate(pkg.lines, 1):
            if line != '\n':
                lastlineempty = False
                if line[-2:-1] == ' ' or line[-2:-1] == '\t':
                    trailing.append(lineno)
                elif line[0] == ' ':
                    leading.append(lineno)
                if indent_regexp.match(line):
                    indent.append(lineno)
            elif lastlineempty:
                double_empty.append(lineno)
            else:
                lastlineempty = True
        if trailing:
            yield WhitespaceFound('trailing', trailing, pkg=pkg)
        if leading:
            yield WhitespaceFound('leading', leading, pkg=pkg)
        if indent:
            yield WrongIndentFound(indent, pkg=pkg)
        if double_empty:
            yield DoubleEmptyLine(double_empty, pkg=pkg)
        if lastlineempty:
            yield TrailingEmptyLine(pkg=pkg)

        # Dealing with empty ebuilds is just paranoia
        if pkg.lines and not pkg.lines[-1].endswith('\n'):
            yield NoFinalNewline(pkg=pkg)
