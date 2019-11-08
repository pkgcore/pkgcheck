from itertools import chain

from pkgcore.ebuild.eapi import EAPI
from pkgcore.test.misc import FakeRepo

from pkgcheck.checks import codingstyle

from .. import misc


class TestBadCommandsCheck(misc.ReportTestCase):

    check_kls = codingstyle.BadCommandsCheck
    check = codingstyle.BadCommandsCheck(None)

    def mk_pkg(self, eapi='0', lines=()):
        return misc.FakePkg("dev-util/diff-0.5", data={'EAPI': eapi}, lines=lines)

    def test_no_matches(self):
        fake_src = [
            'insinto /usr/share/${PN}\n',
            '\n',
            'doins -r foobar\n',
        ]
        self.assertNoReport(self.check, self.mk_pkg(lines=fake_src))

    def test_deprecated_cmds(self):
        for eapi_str, eapi in EAPI.known_eapis.items():
            for command in eapi.bash_cmds_deprecated:
                # commented lines are skipped
                line = f'{command} foo bar'
                pkg = self.mk_pkg(eapi_str, lines=[f'#{line}'])
                self.assertNoReport(self.check, pkg)

                pkg = self.mk_pkg(eapi_str, lines=[line])
                r = self.assertReport(self.check, pkg)
                assert isinstance(r, codingstyle.DeprecatedEapiCommand)
                assert r.command == command
                assert r.eapi == eapi_str
                assert r.line == line
                assert r.lineno == 1
                assert f"'{command}' deprecated in EAPI {eapi_str}" in str(r)

    def test_banned_cmds(self):
        for eapi_str, eapi in EAPI.known_eapis.items():
            for command in eapi.bash_cmds_banned:
                # commented lines are skipped
                line = f'{command} foo bar'
                pkg = self.mk_pkg(eapi_str, lines=[f'#{line}'])
                self.assertNoReport(self.check, pkg)

                pkg = self.mk_pkg(eapi_str, lines=[line])
                r = self.assertReport(self.check, pkg)
                assert isinstance(r, codingstyle.BannedEapiCommand)
                assert r.command == command
                assert r.eapi == eapi_str
                assert r.line == line
                assert r.lineno == 1
                assert f"'{command}' banned in EAPI {eapi_str}" in str(r)


class TestBadInsIntoUsage(misc.ReportTestCase):

    check_kls = codingstyle.BadInsIntoCheck

    def test_insinto(self):
        fake_src = [
            "# This is our first fake ebuild\n",
            "\n",
            "\tinsinto /usr/bin\n",
            "\tinsinto /etc/env.d\n",
            "\tinsinto /etc/env.d/foo\n",
            "\tinsinto /etc/conf.d\n",
            "\tinsinto /etc/init.d/\n",
            "\tinsinto /etc/pam.d\n",
            "\tinsinto /usr/share/applications\n",
            "\tinsinto /usr/share/applications/\n",
            "\tinsinto //usr/share//applications//\n",
            "# That's it for now\n",
        ]
        fake_pkg = misc.FakePkg("dev-util/diffball-0.5", lines=fake_src)

        bad = (
            "/etc/env.d", "/etc/conf.d", "/etc/init.d", "/etc/pam.d",
            "/usr/share/applications", "/usr/share/applications",
            "//usr/share//applications",
        )
        check = self.check_kls(None)

        reports = self.assertReports(check, fake_pkg)
        for r, path in zip(reports, bad):
            assert path in str(r)

    def test_docinto(self):
        check = self.check_kls(None)
        for path in ('${PF}', '${P}', '${PF}/examples'):
            for eapi_str, eapi in EAPI.known_eapis.items():
                fake_src = [f'\tinsinto /usr/share/doc/{path}\n']
                fake_pkg = misc.FakePkg(
                    "dev-util/diff-0.5", data={'EAPI': eapi_str}, lines=fake_src)
                if eapi.options.dodoc_allow_recursive:
                    r = self.assertReport(check, fake_pkg)
                    assert path in str(r)
                else:
                    self.assertNoReport(check, fake_pkg)


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

        fake_src = [
            "# This is our first fake ebuild\n",
            "\n",
        ]
        for src, dest in chain.from_iterable((absolute, relative, unhandled)):
            fake_src.append(f"\tdosym {src} {dest}\n")
        fake_src.append("# That's it for now\n")
        fake_pkg = misc.FakePkg("dev-util/diffball-0.5", lines=fake_src)

        check = self.check_kls(None)
        reports = self.assertReports(check, fake_pkg)
        abspaths = [x.abspath for x in reports]

        assert len(reports) == len(absolute)
        assert abspaths == [x[0] for x in absolute]
        for r, abspath in zip(reports, absolute):
            assert abspath[0] in str(r)


class TestPathVariablesCheck(misc.ReportTestCase):

    check_kls = codingstyle.PathVariablesCheck
    check = check_kls(None)

    def _found(self, cls, suffix=''):
        # check single and multiple matches across all specified variables
        for lines in (1, 2):
            for path_var in self.check_kls.variables:
                fake_src = ["src_install() {\n"]
                for x in range(lines):
                    fake_src.append(f'   rm "${{{path_var}{suffix}}}"a/file{x} || die\n')
                fake_src.extend(["}\n", "\n"])
                for eapi_str, eapi in EAPI.known_eapis.items():
                    fake_pkg = misc.FakePkg(
                        "dev-util/diff-0.5", data={'EAPI': eapi_str}, lines=fake_src)
                    if eapi.options.trailing_slash:
                        self.assertNoReport(self.check, fake_pkg)
                    else:
                        r = self.assertReport(self.check, fake_pkg)
                        assert isinstance(r, cls)
                        assert r.match == f'${{{path_var}{suffix}}}'
                        assert r.lines == tuple(x + 2 for x in range(lines))
                        assert path_var in str(r)

    def _unfound(self, cls, suffix=''):
        for path_var in self.check_kls.variables:
            fake_src = [
                "src_install() {\n",
                f'   local var="${{{path_var}}}_foo"\n',
                f'   rm "${{{path_var}}}"/a/random/file || die\n',
                "}\n",
                "\n",
            ]
            for eapi_str, eapi in EAPI.known_eapis.items():
                fake_pkg = misc.FakePkg(
                    "dev-util/diffball-0.5", data={'EAPI': eapi_str}, lines=fake_src)
                self.assertNoReport(self.check, fake_pkg)

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
            '   cp foo.py "${ED}$(python_get_sitedir)"\n',
            # test non-match
            '   cp foo.py "${D%/}$(python_get_sitedir)"\n',
            # test slash-strip
            '   cp foo.py "${ED%/}$(python_get_sitedir)"\n',
            # test extra slash
            '   cp foo.py "${ED}/$(python_get_sitedir)"\n',
            # test variable variant
            '   cp foo.py "${ED}${PYTHON_SITEDIR}"\n',
            # test silly mistake
            '   cp foo "${ED}${EPREFIX}/foo/bar"\n',
            # function variants
            '   insinto "$(python_get_sitedir)"\n',
            '   exeinto "${EPREFIX}/foo/bar"\n',
            '   fowners foo:bar "$(python_get_sitedir)/foo/bar.py"\n',
            '   dodir /foo/bar "${EPREFIX}"/bar/baz\n',
            # commented lines aren't flagged for double prefix usage
            '#  exeinto "${EPREFIX}/foo/bar"\n',
            '}\n'
        ]
        fake_pkg = misc.FakePkg("dev-util/diffball-0.5", lines=fake_src)
        r = self.assertReports(self.check, fake_pkg)
        cls = codingstyle.DoublePrefixInPath
        expected_results = (
            ('${ED}$(python_get_sitedir)', 2),
            ('${ED%/}$(python_get_sitedir)', 4),
            ('${ED}/$(python_get_sitedir)', 5),
            ('${ED}${PYTHON_SITEDIR}', 6),
            ('${ED}${EPREFIX}', 7),
            ('insinto "$(python_get_sitedir)', 8),
            ('exeinto "${EPREFIX}', 9),
            ('fowners foo:bar "$(python_get_sitedir)', 10),
            ('dodir /foo/bar "${EPREFIX}', 11),
        )
        assert len(r) == len(expected_results)
        for res, exp in zip(r, expected_results):
            assert isinstance(res, cls)
            assert res.match == exp[0]
            assert res.lines == (exp[1],)
            assert exp[0] in str(res)

    def test_double_prefix_unfound(self):
        fake_src = [
            'src_install() {\n',
            '    cp foo.py "${D}$(python_get_sitedir)"\n',
            '    cp foo "${D}${EPREFIX}/foo/bar"\n',
            '    insinto /foo/bar\n',
            # potential false positives: stripping prefix
            '    insinto "${MYVAR#${EPREFIX}}"\n',
            '    insinto "${MYVAR#"${EPREFIX}"}"\n',
            # combined commands
            '    dodir /etc/env.d && echo "FOO=${EPREFIX}"\n',
            '}\n'
        ]
        fake_pkg = misc.FakePkg("dev-util/diffball-0.5", lines=fake_src)
        self.assertNoReport(self.check, fake_pkg)


class TestObsoleteUri(misc.ReportTestCase):

    check_kls = codingstyle.ObsoleteUriCheck

    def test_github_archive_uri(self):
        uri = 'https://github.com/foo/bar/archive/${PV}.tar.gz'
        fake_src = [
            f'SRC_URI="{uri} -> ${{P}}.tar.gz"\n'
        ]
        fake_pkg = misc.FakePkg("dev-util/diffball-0.5", lines=fake_src)
        self.assertNoReport(self.check_kls(None), fake_pkg)

    def test_commented_github_tarball_uri(self):
        uri = 'https://github.com/foo/bar/tarball/${PV}'
        fake_src = [
            '# github tarball\n',
            '\n',
            f'# {uri}\n'
        ]
        fake_pkg = misc.FakePkg("dev-util/diffball-0.5", lines=fake_src)
        self.assertNoReport(self.check_kls(None), fake_pkg)

    def test_github_tarball_uri(self):
        uri = 'https://github.com/foo/bar/tarball/${PV}'
        fake_src = [
            f'SRC_URI="{uri} -> ${{P}}.tar.gz"\n'
        ]

        fake_pkg = misc.FakePkg("dev-util/diffball-0.5", lines=fake_src)
        r = self.assertReport(self.check_kls(None), fake_pkg)
        assert r.line == 1
        assert r.uri == uri
        assert (r.replacement ==
                'https://github.com/foo/bar/archive/${PV}.tar.gz')
        assert uri in str(r)

    def test_github_zipball_uri(self):
        uri = 'https://github.com/foo/bar/zipball/${PV}'
        fake_src = [
            f'SRC_URI="{uri} -> ${{P}}.zip"\n'
        ]

        fake_pkg = misc.FakePkg("dev-util/diffball-0.5", lines=fake_src)
        r = self.assertReport(self.check_kls(None), fake_pkg)
        assert r.line == 1
        assert r.uri == uri
        assert (r.replacement ==
                'https://github.com/foo/bar/archive/${PV}.tar.gz')
        assert uri in str(r)

    def test_gitlab_archive_uri(self):
        uri = 'https://gitlab.com/foo/bar/-/archive/${PV}/${P}.tar.gz'
        fake_src = [
            f'SRC_URI="{uri}"\n'
        ]
        fake_pkg = misc.FakePkg("dev-util/diffball-0.5", lines=fake_src)
        self.assertNoReport(self.check_kls(None), fake_pkg)

    def test_gitlab_tar_gz_uri(self):
        uri = 'https://gitlab.com/foo/bar/repository/archive.tar.gz?ref=${PV}'
        fake_src = [
            f'SRC_URI="{uri} -> ${{P}}.tar.gz"\n'
        ]

        fake_pkg = misc.FakePkg("dev-util/diffball-0.5", lines=fake_src)
        r = self.assertReport(self.check_kls(None), fake_pkg)
        assert r.line == 1
        assert r.uri == uri
        assert (r.replacement ==
                'https://gitlab.com/foo/bar/-/archive/${PV}/bar-${PV}.tar.gz')
        assert uri in str(r)

    def test_gitlab_tar_bz2_uri(self):
        uri = 'https://gitlab.com/foo/bar/repository/archive.tar.bz2?ref=${PV}'
        fake_src = [
            f'SRC_URI="{uri} -> ${{P}}.tar.bz2"\n'
        ]

        fake_pkg = misc.FakePkg("dev-util/diffball-0.5", lines=fake_src)
        r = self.assertReport(self.check_kls(None), fake_pkg)
        assert r.line == 1
        assert r.uri == uri
        assert (r.replacement ==
                'https://gitlab.com/foo/bar/-/archive/${PV}/bar-${PV}.tar.bz2')
        assert uri in str(r)

    def test_gitlab_zip_uri(self):
        uri = 'https://gitlab.com/foo/bar/repository/archive.zip?ref=${PV}'
        fake_src = [
            f'SRC_URI="{uri} -> ${{P}}.zip"\n'
        ]

        fake_pkg = misc.FakePkg("dev-util/diffball-0.5", lines=fake_src)
        r = self.assertReport(self.check_kls(None), fake_pkg)
        assert r.line == 1
        assert r.uri == uri
        assert (r.replacement ==
                'https://gitlab.com/foo/bar/-/archive/${PV}/bar-${PV}.zip')
        assert uri in str(r)


class TestEbuildHeaderCheck(misc.ReportTestCase):

    check_kls = codingstyle.EbuildHeaderCheck

    def mk_pkg(self, **kwargs):
        return misc.FakePkg("dev-util/diffball-0.5", **kwargs)

    def test_empty_file(self):
        fake_pkg = self.mk_pkg(lines=())
        self.assertNoReport(self.check_kls(None), fake_pkg)

    def test_good_copyright(self):
        good_copyrights = [
            '# Copyright 1999-2019 Gentoo Authors\n',
            '# Copyright 2019 Gentoo Authors\n',
            '# Copyright 2010-2017 Gentoo Authors\n',
        ]
        for line in good_copyrights:
            fake_src = [line, self.check_kls.license_header]
            fake_pkg = self.mk_pkg(lines=fake_src)
            self.assertNoReport(self.check_kls(None), fake_pkg)

    def test_invalid_copyright(self):
        bad_copyrights = [
            '# Copyright (c) 1999-2019 Gentoo Authors\n',
            '# Copyright Gentoo Authors\n',
            '# Gentoo Authors\n',
            '# Here is entirely random text\n',
            '\n',
        ]
        for line in bad_copyrights:
            fake_src = [line, self.check_kls.license_header]
            fake_pkg = self.mk_pkg(lines=fake_src)
            r = self.assertReport(self.check_kls(None), fake_pkg)
            assert isinstance(r, codingstyle.InvalidCopyright)
            assert line.strip() in str(r)

    def test_new_foundation_copyright(self):
        """Foundation copyright on new ebuilds triggers the report."""
        bad_copyrights = [
            '# Copyright 1999-2019 Gentoo Foundation\n',
            '# Copyright 2019 Gentoo Foundation\n',
            '# Copyright 3125 Gentoo Foundation\n',
            '# Copyright 2010-2021 Gentoo Foundation\n',
        ]
        for line in bad_copyrights:
            fake_src = [line, self.check_kls.license_header]
            fake_pkg = self.mk_pkg(lines=fake_src)
            r = self.assertReport(self.check_kls(None), fake_pkg)
            assert isinstance(r, codingstyle.OldGentooCopyright)
            assert line.strip() in str(r)

    def test_old_foundation_copyright(self):
        """Foundation copyright on old ebuilds does not trigger false positives."""
        good_copyrights = [
            '# Copyright 1999-2018 Gentoo Foundation\n',
            '# Copyright 2016 Gentoo Foundation\n',
            '# Copyright 2010-2017 Gentoo Foundation\n',
        ]
        for line in good_copyrights:
            fake_src = [line, self.check_kls.license_header]
            fake_pkg = self.mk_pkg(lines=fake_src)
            self.assertNoReport(self.check_kls(None), fake_pkg)

    def test_non_gentoo_authors_copyright_in_gentoo(self):
        """Ebuilds in the gentoo repo must use 'Gentoo Authors'."""
        bad_copyrights = [
            '# Copyright 1999-2019 D. E. Veloper\n',
            '# Copyright 2019 辣鸡汤\n',
        ]
        for line in bad_copyrights:
            fake_src = [line, self.check_kls.license_header]
            fake_pkg = self.mk_pkg(lines=fake_src)
            r = self.assertReport(self.check_kls(None), fake_pkg)
            assert isinstance(r, codingstyle.NonGentooAuthorsCopyright)
            assert line.strip() in str(r)

    def test_license_headers(self):
        copyright = '# Copyright 1999-2019 Gentoo Authors\n'
        fake_src = [copyright, self.check_kls.license_header]
        fake_pkg = self.mk_pkg(lines=fake_src)
        self.assertNoReport(self.check_kls(None), fake_pkg)

        bad_license_headers = [
            '',
            '\n',
            f'{self.check_kls.license_header} ',
            f' {self.check_kls.license_header}',
            '# Distributed under the terms of the GNU General Public License v3'
        ]
        for line in bad_license_headers:
            fake_src = [copyright, line]
            fake_pkg = self.mk_pkg(lines=fake_src)
            r = self.assertReport(self.check_kls(None), fake_pkg)
            assert isinstance(r, codingstyle.InvalidLicenseHeader)
            assert line.strip() in str(r)


class TestRawSrcUriCheck(misc.ReportTestCase):

    check_kls = codingstyle.RawSrcUriCheck

    def mk_pkg(self, **kwargs):
        return misc.FakePkg("dev-util/diffball-0.5", **kwargs)

    def test_single_line(self):
        fake_src = ['HOMEPAGE="https://example.com/"\n',
                    'SRC_URI="${HOMEPAGE}/${P}.tar.bz2"\n']
        fake_pkg = self.mk_pkg(lines=fake_src)
        r = self.assertReport(self.check_kls(None), fake_pkg)
        assert isinstance(r, codingstyle.HomepageInSrcUri)
        assert str(r) == '${HOMEPAGE} in SRC_URI'

    def test_multi_line(self):
        fake_src = ['HOMEPAGE="https://example.com/"\n',
                    'SRC_URI="https://example.org/${P}-manpages.tar.bz2\n',
                    '\t${HOMEPAGE}/${P}.tar.bz2"\n']
        fake_pkg = self.mk_pkg(lines=fake_src)
        r = self.assertReport(self.check_kls(None), fake_pkg)
        assert isinstance(r, codingstyle.HomepageInSrcUri)

    def test_no_match(self):
        fake_src = ['HOMEPAGE="https://example.com/"\n',
                    'SRC_URI="https://example.com/${P}.tar.bz2"\n']
        fake_pkg = self.mk_pkg(lines=fake_src)
        self.assertNoReport(self.check_kls(None), fake_pkg)

    def test_no_false_positive(self):
        fake_src = ['HOMEPAGE="https://example.com/"\n',
                    'SRC_URI="https://example.com/${P}.tar.bz2"\n',
                    '# ${HOMEPAGE} must not be used here\n']
        fake_pkg = self.mk_pkg(lines=fake_src)
        self.assertNoReport(self.check_kls(None), fake_pkg)

    def test_dynamic_src_uri(self):
        fake_src = ['SRC_URI="https://example.com/${PV}/${P}.tar.bz2"\n']
        fake_pkg = self.mk_pkg(lines=fake_src)
        self.assertNoReport(self.check_kls(None), fake_pkg)

    def test_static_package_src_uri(self):
        fake_src = ['SRC_URI="https://example.com/diffball-0.5.tar.bz2"\n']
        fake_pkg = self.mk_pkg(lines=fake_src)
        r = self.assertReport(self.check_kls(None), fake_pkg)
        assert isinstance(r, codingstyle.StaticSrcUri)
        assert r.static_str == 'diffball-0.5.tar.bz2'

    def test_static_package_version_src_uri(self):
        fake_src = ['SRC_URI="https://example.com/0.5/${P}.tar.bz2"\n']
        fake_pkg = self.mk_pkg(lines=fake_src)
        r = self.assertReport(self.check_kls(None), fake_pkg)
        assert isinstance(r, codingstyle.StaticSrcUri)
        assert r.static_str == '0.5'

    def test_multi_static_src_uri(self):
        fake_src = ['SRC_URI="https://example.com/0.5/diffball-0.5.tar.bz2"\n']
        fake_pkg = self.mk_pkg(lines=fake_src)
        for r in self.assertReports(self.check_kls(None), fake_pkg):
            assert isinstance(r, codingstyle.StaticSrcUri)
