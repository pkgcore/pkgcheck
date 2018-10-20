from snakeoil.test import TestCase

from pkgcheck.checks import whitespace

from . import misc


class WhitespaceCheckTest(misc.ReportTestCase, TestCase):
    """Various whitespace related test support."""

    check_kls = whitespace.WhitespaceCheck

    def setUp(self):
        self.check = whitespace.WhitespaceCheck(None, None)


class TestWhitespaceFound(WhitespaceCheckTest):

    def test_leading(self):
        fake_pkg = misc.FakePkg("dev-util/diffball-0.5")
        fake_src = []
        fake_src.append("# This is our first fake ebuild\n")
        fake_src.append(" # This line contains a leading whitespace\n")
        fake_src.append("# That's it for now\n")

        r = self.assertReport(self.check, [fake_pkg, fake_src])
        assert isinstance(r, whitespace.WhitespaceFound)
        assert r.lines == (2,)
        assert 'leading whitespace' in str(r)

    def test_trailing(self):
        fake_pkg = misc.FakePkg("dev-util/diffball-0.5")
        fake_src = []
        fake_src.append("# This is our first fake ebuild\n")
        fake_src.append("# This line contains a trailing whitespace \n")
        fake_src.append("# That's it for now\n")

        r = self.assertReport(self.check, [fake_pkg, fake_src])
        assert isinstance(r, whitespace.WhitespaceFound)
        assert r.lines == (2,)
        assert 'trailing whitespace' in str(r)


class TestWrongIndentFound(WhitespaceCheckTest):

    def test_it(self):
        fake_pkg = misc.FakePkg("dev-util/diffball-0.5")
        fake_src = []
        fake_src.append("# This is our first fake ebuild\n")
        fake_src.append("\t \tBad indentation\n")
        fake_src.append("# That's it for now\n")

        r = self.assertReport(self.check, [fake_pkg, fake_src])
        assert isinstance(r, whitespace.WrongIndentFound)
        assert r.lines == (2,)
        assert 'whitespace in indentation' in str(r)


class TestDoubleEmptyLine(WhitespaceCheckTest):

    def test_it(self):
        fake_pkg = misc.FakePkg("dev-util/diffball-0.5")
        fake_src = []
        fake_src.append("# This is our first fake ebuild\n")
        fake_src.append("\n")
        fake_src.append("\n")
        fake_src.append("# That's it for now\n")

        r = self.assertReport(self.check, [fake_pkg, fake_src])
        assert isinstance(r, whitespace.DoubleEmptyLine)
        assert r.lines == (3,)
        assert 'unneeded empty line' in str(r)


class TestNoNewLineOnEnd(WhitespaceCheckTest):

    def test_it(self):
        fake_pkg = misc.FakePkg("dev-util/diffball-0.5")
        fake_src = []
        fake_src.append("# This is our first fake ebuild\n")
        fake_src.append("# That's it for now")

        r = self.assertReport(self.check, [fake_pkg, fake_src])
        assert isinstance(r, whitespace.NoFinalNewline)
        assert 'lacks an ending newline' in str(r)


class TestTrailingNewLineOnEnd(WhitespaceCheckTest):

    def test_it(self):
        fake_pkg = misc.FakePkg("dev-util/diffball-0.5")
        fake_src = []
        fake_src.append("# This is our first fake ebuild\n")
        fake_src.append("# That's it for now\n")
        fake_src.append("\n")

        r = self.assertReport(self.check, [fake_pkg, fake_src])
        assert isinstance(r, whitespace.TrailingEmptyLine)
        assert 'trailing blank line(s)' in str(r)


class TestMultiReport(WhitespaceCheckTest):

    def test_it(self):
        fake_pkg = misc.FakePkg("dev-util/diffball-0.5")
        fake_src = []
        fake_src.append("# This is our first fake ebuild\n")
        fake_src.append(" # This line contains a leading whitespace\n")
        fake_src.append("# This line contains a trailing whitespace \n")
        fake_src.append("# This line contains a trailing tab\t\n")
        fake_src.append("\t \t#The first whitey is bad...\n")
        fake_src.append("\t\t #... the second one is fine\n")
        fake_src.append("\n")
        fake_src.append("\n")
        fake_src.append("# That's it for now\n")

        reports = self.assertReports(self.check, [fake_pkg, fake_src])
        assert len(reports) == 4
