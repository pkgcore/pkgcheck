"""Various whitespace-related checks."""

import re
from typing import NamedTuple

from .. import results, sources
from . import Check, OptionalCheck


class _Whitespace(results.LinesResult, results.Style): ...


class WhitespaceFound(_Whitespace):
    """Leading or trailing whitespace found."""

    def __init__(self, leadtrail, **kwargs):
        super().__init__(**kwargs)
        self.leadtrail = leadtrail

    @property
    def desc(self):
        return f"ebuild has {self.leadtrail} whitespace {self.lines_str}"


class WrongIndentFound(_Whitespace):
    """Incorrect indentation whitespace found."""

    @property
    def desc(self):
        return f"ebuild has whitespace in indentation {self.lines_str}"


class DoubleEmptyLine(_Whitespace):
    """Unneeded blank lines found."""

    @property
    def desc(self):
        return f"ebuild has unneeded empty line {self.lines_str}"


class TrailingEmptyLine(results.VersionResult, results.Style):
    """Unneeded trailing blank lines found."""

    desc = "ebuild has trailing blank line(s)"


class NoFinalNewline(results.VersionResult, results.Style):
    """Ebuild's last line does not have a final newline."""

    desc = "ebuild lacks an ending newline"


class BadWhitespaceCharacter(results.LineResult, results.Warning):
    """Ebuild uses whitespace that isn't a tab, newline, or single space.

    Bash does not treat unicode whitespace characters as regular whitespace so
    commands or operators separated by such characters will be treated as one
    string. This usually causes execution errors if the characters are used for
    separation purposes outside of comments or regular strings.
    """

    def __init__(self, char, position, **kwargs):
        super().__init__(**kwargs)
        self.char = char
        self.position = position

    @property
    def desc(self):
        return (
            f"bad whitespace character {self.char} on line {self.lineno}"
            f", char {self.position}: {self.line}"
        )


class MissingEAPIBlankLine(results.VersionResult, results.Style):
    """Missing blank line after ``EAPI=`` assignment."""

    desc = "missing blank line after EAPI= assignment"


class WhitespaceData(NamedTuple):
    """Data format to register hardcoded list of bad whitespace characters."""

    unicode_version: str
    chars: tuple


whitespace_data = WhitespaceData(
    unicode_version="12.1.0",
    chars=(
        "\x0b",
        "\x0c",
        "\r",
        "\x1c",
        "\x1d",
        "\x1e",
        "\x1f",
        "\x85",
        "\xa0",
        "\u1680",
        "\u2000",
        "\u2001",
        "\u2002",
        "\u2003",
        "\u2004",
        "\u2005",
        "\u2006",
        "\u2007",
        "\u2008",
        "\u2009",
        "\u200a",
        "\u2028",
        "\u2029",
        "\u202f",
        "\u205f",
        "\u3000",
    ),
)


class WhitespaceCheck(Check):
    """Scan ebuild for useless whitespace."""

    _source = sources.EbuildFileRepoSource
    known_results = frozenset(
        {
            WhitespaceFound,
            WrongIndentFound,
            DoubleEmptyLine,
            TrailingEmptyLine,
            NoFinalNewline,
            BadWhitespaceCharacter,
        }
    )

    _indent_regex = re.compile("^\t* \t+")

    def __init__(self, *args):
        super().__init__(*args)
        bad_whitespace = "".join(whitespace_data.chars)
        self.bad_whitespace_regex = re.compile(rf"(?P<char>[{bad_whitespace}])")

    def feed(self, pkg):
        lastlineempty = False
        trailing = []
        leading = []
        indent = []
        double_empty = []

        for lineno, line in enumerate(pkg.lines, 1):
            for match in self.bad_whitespace_regex.finditer(line):
                yield BadWhitespaceCharacter(
                    repr(match.group("char")),
                    match.end("char"),
                    line=repr(line),
                    lineno=lineno,
                    pkg=pkg,
                )

            if line != "\n":
                lastlineempty = False
                if line[-2:-1] == " " or line[-2:-1] == "\t":
                    trailing.append(lineno)
                elif line[0] == " ":
                    leading.append(lineno)
                if self._indent_regex.match(line):
                    indent.append(lineno)
            elif lastlineempty:
                double_empty.append(lineno)
            else:
                lastlineempty = True
        if trailing:
            yield WhitespaceFound("trailing", lines=trailing, pkg=pkg)
        if leading:
            yield WhitespaceFound("leading", lines=leading, pkg=pkg)
        if indent:
            yield WrongIndentFound(indent, pkg=pkg)
        if double_empty:
            yield DoubleEmptyLine(double_empty, pkg=pkg)
        if lastlineempty:
            yield TrailingEmptyLine(pkg=pkg)

        # Dealing with empty ebuilds is just paranoia
        if pkg.lines and not pkg.lines[-1].endswith("\n"):
            yield NoFinalNewline(pkg=pkg)


class MissingWhitespaceCheck(OptionalCheck):
    """Scan ebuild for missing whitespace."""

    _source = sources.EbuildFileRepoSource
    known_results = frozenset(
        {
            MissingEAPIBlankLine,
        }
    )

    def feed(self, pkg):
        eapi_lineno = None

        for lineno, line in enumerate(pkg.lines, 1):
            if line.startswith("EAPI="):
                eapi_lineno = lineno
            elif eapi_lineno is not None and lineno == eapi_lineno + 1 and line != "\n":
                yield MissingEAPIBlankLine(pkg=pkg)
