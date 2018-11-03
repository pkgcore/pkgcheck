from itertools import chain

from pkgcore.ebuild.eapi import EAPI

from pkgcheck.checks import codingstyle

from .. import misc


class TestBadInsIntoUsage(misc.ReportTestCase):

    check_kls = codingstyle.BadInsIntoCheck

    def test_it(self):
        fake_pkg = misc.FakePkg("dev-util/diffball-0.5")
        fake_src = [
            "# This is our first fake ebuild\n",
            "\n",
            "\tinsinto /usr/bin\n",
            "\tinsinto /etc/env.d\n",
            "\tinsinto /etc/conf.d\n",
            "\tinsinto /etc/init.d/\n",
            "\tinsinto /etc/pam.d\n",
            "\tinsinto /usr/share/applications\n",
            "\tinsinto /usr/share/applications/\n",
            "\tinsinto //usr/share//applications//\n",
            "\tinsinto /etc/cron.d\n",
            "\tinsinto /etc/cron.hourly\n",
            "\tinsinto /etc/cron.daily\n",
            "\tinsinto /etc/cron.weekly\n",
            "# That's it for now\n",
        ]

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

    check_kls = codingstyle.AbsoluteSymlinkCheck

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
        fake_src = [
            "# This is our first fake ebuild\n",
            "\n",
        ]
        for src, dest in chain.from_iterable((absolute, relative, unhandled)):
            fake_src.append(f"\tdosym {src} {dest}\n")
        fake_src.append("# That's it for now\n")

        check = self.check_kls(options=None)
        reports = self.assertReports(check, [fake_pkg, fake_src])
        abspaths = [x.abspath for x in reports]

        assert len(reports) == len(absolute)
        assert abspaths == [x[0].strip('"\'').split()[0] for x in absolute]


class TestMissingSlash(misc.ReportTestCase):

    check_kls = codingstyle.MissingSlashCheck
    check = check_kls(options=None)

    def test_it(self):
        for path_var in self.check_kls.variables:
            fake_src = [
                "src_install() {\n",
                f'   rm "${{{path_var}}}"a/random/file || die\n'
                "}\n",
                "\n",
            ]
            for eapi_str, eapi in EAPI.known_eapis.items():
                fake_pkg = misc.FakePkg("dev-util/diffball-0.5", data={'EAPI': eapi_str})
                if eapi.options.trailing_slash:
                    self.assertNoReport(self.check, [fake_pkg, fake_src])
                else:
                    r = self.assertReport(self.check, [fake_pkg, fake_src])
                    assert r.variable == f'${{{path_var}}}'
                    assert r.line == 2
                    assert path_var in str(r)
