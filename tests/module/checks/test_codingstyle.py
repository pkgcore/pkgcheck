from itertools import chain

from pkgcore.ebuild.eapi import EAPI
from pkgcore.test.misc import FakeRepo

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
        for r, path in zip(reports, bad):
            assert path in str(r)


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
        assert abspaths == [x[0] for x in absolute]
        for r, abspath in zip(reports, absolute):
            assert abspath[0] in str(r)


class TestPathVariablesCheck(misc.ReportTestCase):

    check_kls = codingstyle.PathVariablesCheck
    check = check_kls(options=None)

    def _found(self, cls, suffix=''):
        # check single and multiple matches across all specified variables
        for lines in (1, 2):
            for path_var in self.check_kls.variables:
                fake_src = ["src_install() {\n"]
                for x in range(lines):
                    fake_src.append(f'   rm "${{{path_var}{suffix}}}"a/file{x} || die\n')
                fake_src.extend(["}\n", "\n"])
                for eapi_str, eapi in EAPI.known_eapis.items():
                    fake_pkg = misc.FakePkg("dev-util/diff-0.5", data={'EAPI': eapi_str})
                    if eapi.options.trailing_slash:
                        self.assertNoReport(self.check, [fake_pkg, fake_src])
                    else:
                        r = self.assertReport(self.check, [fake_pkg, fake_src])
                        assert isinstance(r, cls)
                        assert r.variable == f'${{{path_var}{suffix}}}'
                        assert r.lines == tuple(x + 2 for x in range(lines))
                        assert path_var in str(r)

    def _unfound(self, cls, suffix=''):
        for path_var in self.check_kls.variables:
            fake_src = [
                "src_install() {\n",
                f'   rm "${{S}}"a/random/file || die\n',
                "}\n",
                "\n",
            ]
            for eapi_str, eapi in EAPI.known_eapis.items():
                fake_pkg = misc.FakePkg("dev-util/diffball-0.5", data={'EAPI': eapi_str})
                self.assertNoReport(self.check, [fake_pkg, fake_src])

    def test_missing_found(self):
        self._found(codingstyle.MissingSlash)

    def test_missing_unfound(self):
        self._unfound(codingstyle.MissingSlash)

    def test_unnecessary_found(self):
        self._found(codingstyle.UnnecessarySlashStrip, suffix='%/')

    def test_unnecessary_unfound(self):
        self._unfound(codingstyle.UnnecessarySlashStrip, suffix='%/')

    def test_double_prefix_found(self):
        fake_src = [
            'src_install() {\n',
            '    cp foo.py "${ED}$(python_get_sitedir)"\n',
            # test non-match
            '    cp foo.py "${D%/}$(python_get_sitedir)"\n',
            # test slash-strip
            '    cp foo.py "${ED%/}$(python_get_sitedir)"\n',
            # test extra slash
            '    cp foo.py "${ED}/$(python_get_sitedir)"\n',
            # test variable variant
            '    cp foo.py "${ED}${PYTHON_SITEDIR}"\n',
            # test silly mistake
            '    cp foo "${ED}${EPREFIX}/foo/bar"\n',
            '}\n'
        ]
        fake_pkg = misc.FakePkg("dev-util/diffball-0.5")
        r = self.assertReports(self.check, [fake_pkg, fake_src])
        cls = codingstyle.DoublePrefixInPath
        expected_results = (
            ('${ED}$(python_get_sitedir)', 2),
            ('${ED%/}$(python_get_sitedir)', 4),
            ('${ED}/$(python_get_sitedir)', 5),
            ('${ED}${PYTHON_SITEDIR}', 6),
            ('${ED}${EPREFIX}', 7),
        )
        assert len(r) == len(expected_results)
        for res, exp in zip(r, expected_results):
            assert isinstance(res, cls)
            assert res.variable == exp[0]
            assert res.lines == (exp[1],)
            assert exp[0] in str(res)

    def test_double_prefix_unfound(self):
        fake_src = [
            'src_install() {\n',
            '    cp foo.py "${D}$(python_get_sitedir)"\n'
            '    cp foo "${D}${EPREFIX}/foo/bar"\n'
            '}\n'
        ]
        fake_pkg = misc.FakePkg("dev-util/diffball-0.5")
        self.assertNoReport(self.check, [fake_pkg, fake_src])


class TestObsoleteUri(misc.ReportTestCase):

    check_kls = codingstyle.ObsoleteUriCheck
    fake_pkg = misc.FakePkg("dev-util/diffball-0.5")

    def test_github_archive_uri(self):
        uri = 'https://github.com/foo/bar/archive/${PV}.tar.gz'
        fake_src = [
            f'SRC_URI="{uri} -> ${{P}}.tar.gz"\n'
        ]
        self.assertNoReport(self.check_kls(options=None), [self.fake_pkg, fake_src])

    def test_github_tarball_uri(self):
        uri = 'https://github.com/foo/bar/tarball/${PV}'
        fake_src = [
            f'SRC_URI="{uri} -> ${{P}}.tar.gz"\n'
        ]

        r = self.assertReport(self.check_kls(options=None),
                              [self.fake_pkg, fake_src])
        assert r.line == 1
        assert r.uri == uri
        assert (r.replacement ==
                'https://github.com/foo/bar/archive/${PV}.tar.gz')

    def test_github_zipball_uri(self):
        uri = 'https://github.com/foo/bar/zipball/${PV}'
        fake_src = [
            f'SRC_URI="{uri} -> ${{P}}.zip"\n'
        ]

        r = self.assertReport(self.check_kls(options=None),
                              [self.fake_pkg, fake_src])
        assert r.line == 1
        assert r.uri == uri
        assert (r.replacement ==
                'https://github.com/foo/bar/archive/${PV}.tar.gz')

    def test_gitlab_archive_uri(self):
        uri = 'https://gitlab.com/foo/bar/-/archive/${PV}/${P}.tar.gz'
        fake_src = [
            f'SRC_URI="{uri}"\n'
        ]
        self.assertNoReport(self.check_kls(options=None), [self.fake_pkg, fake_src])

    def test_gitlab_tar_gz_uri(self):
        uri = 'https://gitlab.com/foo/bar/repository/archive.tar.gz?ref=${PV}'
        fake_src = [
            f'SRC_URI="{uri} -> ${{P}}.tar.gz"\n'
        ]

        r = self.assertReport(self.check_kls(options=None),
                              [self.fake_pkg, fake_src])
        assert r.line == 1
        assert r.uri == uri
        assert (r.replacement ==
                'https://gitlab.com/foo/bar/-/archive/${PV}/bar-${PV}.tar.gz')

    def test_gitlab_tar_bz2_uri(self):
        uri = 'https://gitlab.com/foo/bar/repository/archive.tar.bz2?ref=${PV}'
        fake_src = [
            f'SRC_URI="{uri} -> ${{P}}.tar.bz2"\n'
        ]

        r = self.assertReport(self.check_kls(options=None),
                              [self.fake_pkg, fake_src])
        assert r.line == 1
        assert r.uri == uri
        assert (r.replacement ==
                'https://gitlab.com/foo/bar/-/archive/${PV}/bar-${PV}.tar.bz2')

    def test_gitlab_zip_uri(self):
        uri = 'https://gitlab.com/foo/bar/repository/archive.zip?ref=${PV}'
        fake_src = [
            f'SRC_URI="{uri} -> ${{P}}.zip"\n'
        ]

        r = self.assertReport(self.check_kls(options=None),
                              [self.fake_pkg, fake_src])
        assert r.line == 1
        assert r.uri == uri
        assert (r.replacement ==
                'https://gitlab.com/foo/bar/-/archive/${PV}/bar-${PV}.zip')


class TestCopyright(misc.ReportTestCase):

    check_kls = codingstyle.CopyrightCheck

    def mk_pkg(self, repo_id='gentoo'):
        class fake_parent:
            _parent_repo = FakeRepo(repo_id=repo_id)

        return misc.FakePkg("dev-util/diffball-0.5", parent=fake_parent)

    def test_good_copyright(self):
        good_copyrights = [
            '# Copyright 1999-2019 Gentoo Authors\n',
            '# Copyright 2019 Gentoo Authors\n',
            '# Copyright 2010-2017 Gentoo Authors\n',
        ]
        fake_pkg = self.mk_pkg()
        for line in good_copyrights:
            fake_src = [line]
            self.assertNoReport(self.check_kls(options=None),
                                [fake_pkg, fake_src])

    def test_invalid_copyright(self):
        bad_copyrights = [
            '# Copyright (c) 1999-2019 Gentoo Authors\n',
            '# Copyright Gentoo Authors\n',
            '# Gentoo Authors\n',
            '# Here is entirely random text\n',
            '\n',
        ]
        fake_pkg = self.mk_pkg()
        for line in bad_copyrights:
            fake_src = [line]
            r = self.assertReport(self.check_kls(options=None),
                                  [fake_pkg, fake_src])
            assert isinstance(r, codingstyle.InvalidCopyright)

    def test_new_foundation_copyright(self):
        """
        Test that Foundation copyright on new ebuilds triggers the report.
        """
        bad_copyrights = [
            '# Copyright 1999-2019 Gentoo Foundation\n',
            '# Copyright 2019 Gentoo Foundation\n',
            '# Copyright 3125 Gentoo Foundation\n',
            '# Copyright 2010-2021 Gentoo Foundation\n',
        ]
        fake_pkg = self.mk_pkg()
        for line in bad_copyrights:
            fake_src = [line]
            r = self.assertReport(self.check_kls(options=None),
                                  [fake_pkg, fake_src])
            assert isinstance(r, codingstyle.OldGentooCopyright)

    def test_old_foundation_copyright(self):
        """
        Test that Foundation copyright on old ebuilds does not trigger false
        positives.
        """
        good_copyrights = [
            '# Copyright 1999-2018 Gentoo Foundation\n',
            '# Copyright 2016 Gentoo Foundation\n',
            '# Copyright 2010-2017 Gentoo Foundation\n',
        ]
        fake_pkg = self.mk_pkg()
        for line in good_copyrights:
            fake_src = [line]
            self.assertNoReport(self.check_kls(options=None),
                                [fake_pkg, fake_src])

    def test_non_gentoo_authors_copyright_in_gentoo(self):
        """
        Test that ::gentoo ebuilds enforce 'Gentoo Authors'.
        """
        bad_copyrights = [
            '# Copyright 1999-2019 D. E. Veloper\n',
            '# Copyright 2019 辣鸡汤\n',
        ]
        fake_pkg = self.mk_pkg()
        for line in bad_copyrights:
            fake_src = [line]
            r = self.assertReport(self.check_kls(options=None),
                                  [fake_pkg, fake_src])
            assert isinstance(r, codingstyle.NonGentooAuthorsCopyright)

    def test_non_gentoo_authors_copyright_outside_gentoo(self):
        """
        Test that ::gentoo ebuilds enforce 'Gentoo Authors'.
        """
        good_copyrights = [
            '# Copyright 1999-2019 D. E. Veloper\n',
            '# Copyright 2019 辣鸡汤\n',
        ]
        fake_pkg = self.mk_pkg(repo_id='test')
        for line in good_copyrights:
            fake_src = [line]
            self.assertNoReport(self.check_kls(options=None),
                                [fake_pkg, fake_src])
