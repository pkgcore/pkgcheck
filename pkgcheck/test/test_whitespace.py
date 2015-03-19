# Copyright: 2007 Markus Ullmann <jokey@gentoo.org>
# License: BSD/GPL2

from pkgcheck.test import misc
from pkgcheck.whitespace import WhitespaceCheck


class TestStandardWhitespaces(misc.ReportTestCase):

    check_kls = WhitespaceCheck

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

        check = WhitespaceCheck(None, None)

        report = self.assertReports(check,[fake_pkg,fake_src])
        self.assertEqual(len(report), 4)


class TestNoNewLineOnEnd(misc.ReportTestCase):

    check_kls = WhitespaceCheck

    def test_it(self):
        fake_pkg = misc.FakePkg("dev-util/diffball-0.5")
        fake_src = []
        fake_src.append("# This is our first fake ebuild\n")
        fake_src.append("# That's it for now")

        check = WhitespaceCheck(None, None)

        report = self.assertReports(check,[fake_pkg,fake_src])
        self.assertEqual(len(report), 1)


class TestTrailingNewLineOnEnd(misc.ReportTestCase):

    check_kls = WhitespaceCheck

    def test_it(self):
        fake_pkg = misc.FakePkg("dev-util/diffball-0.5")
        fake_src = []
        fake_src.append("# This is our first fake ebuild\n")
        fake_src.append("# That's it for now\n")
        fake_src.append("\n")

        check = WhitespaceCheck(None, None)

        report = self.assertReports(check,[fake_pkg,fake_src])
        self.assertEqual(len(report), 1)

