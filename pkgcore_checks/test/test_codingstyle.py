# Copyright: 2007 Markus Ullmann <jokey@gentoo.org>
# License: GPL2

from pkgcore_checks.test import misc
from pkgcore_checks.codingstyle import BadInsIntoDotDirCheck

class TestBadDotDirUsage(misc.ReportTestCase):

    check_kls = BadInsIntoDotDirCheck

    def test_it(self):
        fake_pkg = misc.FakePkg("dev-util/diffball-0.5")
        fake_src = []
        fake_src.append("# This is our first fake ebuild\n")
        fake_src.append("\n")
        fake_src.append("\tinsinto /usr/bin\n")
        fake_src.append("\tinsinto /etc/env.d\n")
        fake_src.append("\tinsinto /etc/conf.d\n")
        fake_src.append("\tinsinto /etc/init.d\n")
        fake_src.append("# That's it for now\n")
	
        check = BadInsIntoDotDirCheck(None, None)

        report = self.assertReports(check,[fake_pkg, fake_src])
        self.assertEqual(len(report), 3)
