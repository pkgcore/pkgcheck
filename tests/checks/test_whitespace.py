import re
import sys
import unicodedata

from pkgcheck.checks import whitespace

from .. import misc


class WhitespaceCheckTest(misc.ReportTestCase):
    """Various whitespace related test support."""

    check_kls = whitespace.WhitespaceCheck
    check = whitespace.WhitespaceCheck(None)


class TestWhitespaceFound(WhitespaceCheckTest):
    def test_leading(self):
        fake_src = [
            "# This is our first fake ebuild\n",
            " # This line contains a leading whitespace\n",
            "# That's it for now\n",
        ]
        fake_pkg = misc.FakePkg("dev-util/diffball-0.5", lines=fake_src)

        r = self.assertReport(self.check, fake_pkg)
        assert isinstance(r, whitespace.WhitespaceFound)
        assert r.lines == (2,)
        assert "leading whitespace" in str(r)

    def test_trailing(self):
        fake_src = [
            "# This is our first fake ebuild\n",
            "# This line contains a trailing whitespace \n",
            "# That's it for now\n",
        ]
        fake_pkg = misc.FakePkg("dev-util/diffball-0.5", lines=fake_src)

        r = self.assertReport(self.check, fake_pkg)
        assert isinstance(r, whitespace.WhitespaceFound)
        assert r.lines == (2,)
        assert "trailing whitespace" in str(r)


class TestWrongIndentFound(WhitespaceCheckTest):
    def test_it(self):
        fake_src = [
            "# This is our first fake ebuild\n",
            "\t \tBad indentation\n",
            "# That's it for now\n",
        ]
        fake_pkg = misc.FakePkg("dev-util/diffball-0.5", lines=fake_src)

        r = self.assertReport(self.check, fake_pkg)
        assert isinstance(r, whitespace.WrongIndentFound)
        assert r.lines == (2,)
        assert "whitespace in indentation" in str(r)


class TestDoubleEmptyLine(WhitespaceCheckTest):
    def test_it(self):
        fake_src = [
            "# This is our first fake ebuild\n",
            "\n",
            "\n",
            "# That's it for now\n",
        ]
        fake_pkg = misc.FakePkg("dev-util/diffball-0.5", lines=fake_src)

        r = self.assertReport(self.check, fake_pkg)
        assert isinstance(r, whitespace.DoubleEmptyLine)
        assert r.lines == (3,)
        assert "unneeded empty line" in str(r)


class TestNoNewLineOnEnd(WhitespaceCheckTest):
    def test_it(self):
        fake_src = [
            "# This is our first fake ebuild\n",
            "# That's it for now",
        ]
        fake_pkg = misc.FakePkg("dev-util/diffball-0.5", lines=fake_src)

        r = self.assertReport(self.check, fake_pkg)
        assert isinstance(r, whitespace.NoFinalNewline)
        assert "lacks an ending newline" in str(r)


class TestTrailingNewLineOnEnd(WhitespaceCheckTest):
    def test_it(self):
        fake_src = [
            "# This is our first fake ebuild\n",
            "# That's it for now\n",
            "\n",
        ]
        fake_pkg = misc.FakePkg("dev-util/diffball-0.5", lines=fake_src)

        r = self.assertReport(self.check, fake_pkg)
        assert isinstance(r, whitespace.TrailingEmptyLine)
        assert "trailing blank line(s)" in str(r)


def generate_whitespace_data():
    """Generate bad whitespace list for the current python version."""
    all_whitespace_chars = set(
        re.findall(r"\s", "".join(chr(c) for c in range(sys.maxunicode + 1)))
    )
    allowed_whitespace_chars = {"\t", "\n", " "}
    bad_whitespace_chars = tuple(sorted(all_whitespace_chars - allowed_whitespace_chars))
    return whitespace.WhitespaceData(unicodedata.unidata_version, bad_whitespace_chars)


class TestBadWhitespaceCharacter(WhitespaceCheckTest):
    def test_outdated_bad_whitespace_chars(self):
        """Check if the hardcoded bad whitespace character list is outdated."""
        updated_whitespace_data = generate_whitespace_data()
        if updated_whitespace_data.unicode_version != whitespace.whitespace_data.unicode_version:
            assert (
                updated_whitespace_data.chars == whitespace.whitespace_data.chars
            ), f"outdated character list for Unicode version {unicodedata.unidata_version}"

    def test_bad_whitespace_chars(self):
        for char in whitespace.whitespace_data.chars:
            fake_src = [
                "src_prepare() {\n",
                f'\tcd "${{S}}"/cpp ||{char}die\n',
                "}\n",
            ]
            fake_pkg = misc.FakePkg("dev-util/diffball-0.5", lines=fake_src)

            r = self.assertReport(self.check, fake_pkg)
            assert isinstance(r, whitespace.BadWhitespaceCharacter)
            assert f"bad whitespace character {repr(char)} on line 2" in str(r)


class TestMultipleChecks(WhitespaceCheckTest):
    def test_it(self):
        fake_src = [
            "# This is our first fake ebuild\n",
            " # This line contains a leading whitespace\n",
            "# This line contains a trailing whitespace \n",
            "# This line contains a trailing tab\t\n",
            "\t \t#The first whitey is bad...\n",
            "\t\t #... the second one is fine\n",
            "\n",
            "\n",
            "# That's it for now\n",
        ]
        fake_pkg = misc.FakePkg("dev-util/diffball-0.5", lines=fake_src)

        reports = self.assertReports(self.check, fake_pkg)
        assert len(reports) == 4


class TestMissingWhitespaceCheck(misc.ReportTestCase):
    check_kls = whitespace.MissingWhitespaceCheck
    check = whitespace.MissingWhitespaceCheck(None)

    def test_it(self):
        fake_src = [
            "# This is a comment\n",
            "# This is a comment\n",
            "# This is a comment, and no blank line before EAPI\n",
            "EAPI=8\n",
            "inherit fake\n",  # no blank line after EAPI=
        ]
        fake_pkg = misc.FakePkg("dev-util/diffball-0.5", lines=fake_src)

        r = self.assertReport(self.check, fake_pkg)
        assert isinstance(r, whitespace.MissingEAPIBlankLine)
