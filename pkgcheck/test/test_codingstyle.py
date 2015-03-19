# Copyright: 2007 Markus Ullmann <jokey@gentoo.org>
# License: BSD/GPL2

from pkgcheck.test import misc
from pkgcheck.codingstyle import BadInsIntoCheck


class TestBadInsIntoUsage(misc.ReportTestCase):

    check_kls = BadInsIntoCheck

    def test_it(self):
        fake_pkg = misc.FakePkg("dev-util/diffball-0.5")
        fake_src = []
        fake_src.append("# This is our first fake ebuild\n")
        fake_src.append("\n")
        fake_src.append("\tinsinto /usr/bin\n")
        fake_src.append("\tinsinto /etc/env.d\n")
        fake_src.append("\tinsinto /etc/conf.d\n")
        fake_src.append("\tinsinto /etc/init.d/\n")
        fake_src.append("\tinsinto /etc/pam.d\n")
        fake_src.append("\tinsinto /usr/share/applications\n")
        fake_src.append("\tinsinto /usr/share/applications/\n")
        fake_src.append("\tinsinto //usr/share//applications//\n")
        fake_src.append("\tinsinto /etc/cron.d\n")
        fake_src.append("\tinsinto /etc/cron.hourly\n")
        fake_src.append("\tinsinto /etc/cron.daily\n")
        fake_src.append("\tinsinto /etc/cron.weekly\n")
        fake_src.append("# That's it for now\n")

        bad = (
            "/etc/env.d", "/etc/conf.d", "/etc/init.d", "/etc/pam.d",
            "/usr/share/applications", "/usr/share/applications",
            "//usr/share//applications", "/etc/cron.d", "/etc/cron.hourly",
            "/etc/cron.daily", "/etc/cron.weekly")
        check = BadInsIntoCheck(None, None)

        reports = self.assertReports(check, [fake_pkg, fake_src])
        dirs = [x.insintodir for x in reports]
        self.assertEqual(dirs, list(bad))
