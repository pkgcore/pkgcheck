# Copyright: 2007 Markus Ullmann <jokey@gentoo.org>
# License: GPL2

from pkgcore_checks.test import misc
from pkgcore_checks.whitespace import WhitespaceCheck
from pkgcore.interfaces.data_source import read_StringIO

class TestStandardWhitespaces(misc.ReportTestCase):

    def test_it(self):
        fake_pkg = misc.FakePkg("dev-util/diffball-0.5")
        fake_src = []
        fake_src.append("# This is our first fake ebuild\n")
        fake_src.append(" # This line contains a leading whitespace\n")
        fake_src.append("# This line contains a trailing whitespace \n")
        fake_src.append("# This line contains a trailing tab\t\n")
        fake_src.append("\n")
        fake_src.append("\n")
        fake_src.append("# That's it for now\n")
	
        check = WhitespaceCheck(None, None)

        report = self.assertReports(check,[fake_pkg,fake_src])
        self.assertEqual(len(report), 4)


class TestNoNewLineOnEnd(misc.ReportTestCase):

    def test_it(self):
        fake_pkg = misc.FakePkg("dev-util/diffball-0.5")
        fake_src = []
        fake_src.append("# This is our first fake ebuild\n")
        fake_src.append("# That's it for now")
	
        check = WhitespaceCheck(None, None)

        report = self.assertReports(check,[fake_pkg,fake_src])
        self.assertEqual(len(report), 1)


class TestTrailingNewLineOnEnd(misc.ReportTestCase):

    def test_it(self):
        fake_pkg = misc.FakePkg("dev-util/diffball-0.5")
        fake_src = []
        fake_src.append("# This is our first fake ebuild\n")
        fake_src.append("# That's it for now\n")
        fake_src.append("\n")
	
        check = WhitespaceCheck(None, None)

        report = self.assertReports(check,[fake_pkg,fake_src])
        self.assertEqual(len(report), 1)
	
