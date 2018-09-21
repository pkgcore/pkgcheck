from pkgcheck.test import misc
from pkgcheck import whitespace


class WhitespaceCheckTest(misc.ReportTestCase):
    """Various whitespace related test support."""

    check_kls = whitespace.WhitespaceCheck

    def setUp(self):
        self.check = whitespace.WhitespaceCheck(None, None)


class TestStandardWhitespaces(WhitespaceCheckTest):

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

        report = self.assertReports(self.check,[fake_pkg,fake_src])
        assert len(report) == 4


class TestNoNewLineOnEnd(WhitespaceCheckTest):

    def test_it(self):
        fake_pkg = misc.FakePkg("dev-util/diffball-0.5")
        fake_src = []
        fake_src.append("# This is our first fake ebuild\n")
        fake_src.append("# That's it for now")

        report = self.assertReports(self.check,[fake_pkg,fake_src])
        assert len(report) == 1


class TestTrailingNewLineOnEnd(WhitespaceCheckTest):

    def test_it(self):
        fake_pkg = misc.FakePkg("dev-util/diffball-0.5")
        fake_src = []
        fake_src.append("# This is our first fake ebuild\n")
        fake_src.append("# That's it for now\n")
        fake_src.append("\n")

        report = self.assertReports(self.check,[fake_pkg,fake_src])
        assert len(report) == 1
