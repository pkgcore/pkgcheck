from itertools import chain

from pkgcheck.test import misc
from pkgcheck.codingstyle import AbsoluteSymlinkCheck, BadInsIntoCheck


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
        check = self.check_kls(options=None)

        reports = self.assertReports(check, [fake_pkg, fake_src])
        dirs = [x.insintodir for x in reports]
        assert dirs == list(bad)


class TestAbsoluteSymlink(misc.ReportTestCase):

    check_kls = AbsoluteSymlinkCheck

    def test_it(self):
        absolute = (
            ("/bin/blah", "/bin/baz"),
            ('"/bin/blah baz"', "/bin/blahbaz"),
            ("'/bin/blah baz'", "/bin/blahbaz"),
            ("/etc/Boo", "/etc/boo"),
        )

        relative = (
            ("blah", "/bin/baz"),
            ('"blah baz"', "/bin/blahbaz"),
            ("Boo", "/etc/boo"),
        )

        unhandled = (
            ("/crazy/root/dir", "/crazy/symlink"),
        )

        fake_pkg = misc.FakePkg("dev-util/diffball-0.5")
        fake_src = []
        fake_src.append("# This is our first fake ebuild\n")
        fake_src.append("\n")
        for src, dest in chain.from_iterable((absolute, relative, unhandled)):
            fake_src.append(f"\tdosym {src} {dest}\n")
        fake_src.append("# That's it for now\n")

        check = self.check_kls(options=None)
        reports = self.assertReports(check, [fake_pkg, fake_src])
        abspaths = [x.abspath for x in reports]

        assert len(reports) == len(absolute)
        assert abspaths == [x[0].strip('"\'').split()[0] for x in absolute]
