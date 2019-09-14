from itertools import chain

from pkgcore.ebuild.eapi import EAPI
from pkgcore.test.misc import FakeRepo

from pkgcheck.checks import codingstyle

from .. import misc


class TestHttpsAvailableCheck(misc.ReportTestCase):

    check_kls = codingstyle.HttpsAvailableCheck

    @classmethod
    def setup_class(cls):
        cls.check = cls.check_kls(options=None)
        cls.pkg = misc.FakePkg("dev-util/diffball-0.5")

    def test_no_matches(self):
        fake_src = ['HOMEPAGE="http://foobar.com/"\n']
        self.assertNoReport(self.check, [self.pkg, fake_src])

    def test_already_https(self):
        fake_src = ['HOMEPAGE="https://github.com/foo/bar"\n']
        self.assertNoReport(self.check, [self.pkg, fake_src])

    def test_single_match(self):
        fake_src = [f'HOMEPAGE="http://github.com/foo/bar"\n']
        r = self.assertReport(self.check, [self.pkg, fake_src])
        assert isinstance(r, codingstyle.HttpsAvailable)
        assert r.link == 'http://github.com/'
        assert r.lines == (1,)
        assert 'http://github.com/' in str(r)

    def test_multiple_line_matches(self):
        fake_src = [
            'HOMEPAGE="http://foo.apache.org/"\n',
            '\n',
            'SRC_URI="http://foo.apache.org/${P}.tar.bz2"\n',
        ]
        r = self.assertReport(self.check, [self.pkg, fake_src])
        assert isinstance(r, codingstyle.HttpsAvailable)
        assert r.link == 'http://foo.apache.org/'
        assert r.lines == (1, 3)
        assert 'http://foo.apache.org/' in str(r)

    def test_multiple_link_matches(self):
        fake_src = [
            'HOMEPAGE="http://www.kernel.org/foo"\n',
            '\n',
            'SRC_URI="http://sf.net/foo/${P}.tar.bz2"\n',
        ]
        self.assertReports(self.check, [self.pkg, fake_src])


class TestPortageInternalsCheck(misc.ReportTestCase):

    check_kls = codingstyle.PortageInternalsCheck

    @classmethod
    def setup_class(cls):
        cls.check = cls.check_kls(options=None)
        cls.pkg = misc.FakePkg("dev-util/diffball-0.5")

    def test_no_matches(self):
        fake_src = [
            'insinto /usr/share/${PN}\n',
            '\n',
            'doins -r foobar\n',
        ]
        self.assertNoReport(self.check, [self.pkg, fake_src])

    def test_all_internals(self):
        for internal in self.check_kls.INTERNALS:
            fake_src = [f'{internal} foo bar']
            r = self.assertReport(self.check, [self.pkg, fake_src])
            assert isinstance(r, codingstyle.PortageInternals)
            assert r.internal == internal
            assert r.line == 1
            assert internal in str(r)


class TestBadInsIntoUsage(misc.ReportTestCase):

    check_kls = codingstyle.BadInsIntoCheck

    def test_insinto(self):
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
            "# That's it for now\n",
        ]

        bad = (
            "/etc/env.d", "/etc/conf.d", "/etc/init.d", "/etc/pam.d",
            "/usr/share/applications", "/usr/share/applications",
            "//usr/share//applications",
        )
        check = self.check_kls(options=None)

        reports = self.assertReports(check, [fake_pkg, fake_src])
        for r, path in zip(reports, bad):
            assert path in str(r)

    def test_docinto(self):
        check = self.check_kls(options=None)
        for path in ('${PF}', '${P}', '${PF}/examples'):
            for eapi_str, eapi in EAPI.known_eapis.items():
                fake_pkg = misc.FakePkg("dev-util/diff-0.5", data={'EAPI': eapi_str})
                fake_src = [f'\tinsinto /usr/share/doc/{path}\n']
                if eapi.options.dodoc_allow_recursive:
                    r = self.assertReport(check, [fake_pkg, fake_src])
                    assert path in str(r)
                else:
                    self.assertNoReport(check, [fake_pkg, fake_src])


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
                        assert r.match == f'${{{path_var}{suffix}}}'
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
        fake_pkg = misc.FakePkg("dev-util/diffball-0.5")
        r = self.assertReports(self.check, [fake_pkg, fake_src])
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

    def test_commented_github_tarball_uri(self):
        uri = 'https://github.com/foo/bar/tarball/${PV}'
        fake_src = [
            '# github tarball\n',
            '\n',
            f'# {uri}\n'
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
        assert uri in str(r)

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
        assert uri in str(r)

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
        assert uri in str(r)

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
        assert uri in str(r)

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
        assert uri in str(r)


class TestEbuildHeaderCheck(misc.ReportTestCase):

    check_kls = codingstyle.EbuildHeaderCheck

    def mk_pkg(self):
        return misc.FakePkg("dev-util/diffball-0.5")

    def test_empty_file(self):
        fake_src = []
        fake_pkg = self.mk_pkg()
        self.assertNoReport(self.check_kls(options=None), [fake_pkg, fake_src])

    def test_good_copyright(self):
        good_copyrights = [
            '# Copyright 1999-2019 Gentoo Authors\n',
            '# Copyright 2019 Gentoo Authors\n',
            '# Copyright 2010-2017 Gentoo Authors\n',
        ]
        fake_pkg = self.mk_pkg()
        for line in good_copyrights:
            fake_src = [line, self.check_kls.license_header]
            self.assertNoReport(self.check_kls(options=None), [fake_pkg, fake_src])

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
            fake_src = [line, self.check_kls.license_header]
            r = self.assertReport(self.check_kls(options=None), [fake_pkg, fake_src])
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
        fake_pkg = self.mk_pkg()
        for line in bad_copyrights:
            fake_src = [line, self.check_kls.license_header]
            r = self.assertReport(self.check_kls(options=None), [fake_pkg, fake_src])
            assert isinstance(r, codingstyle.OldGentooCopyright)
            assert line.strip() in str(r)

    def test_old_foundation_copyright(self):
        """Foundation copyright on old ebuilds does not trigger false positives."""
        good_copyrights = [
            '# Copyright 1999-2018 Gentoo Foundation\n',
            '# Copyright 2016 Gentoo Foundation\n',
            '# Copyright 2010-2017 Gentoo Foundation\n',
        ]
        fake_pkg = self.mk_pkg()
        for line in good_copyrights:
            fake_src = [line, self.check_kls.license_header]
            self.assertNoReport(self.check_kls(options=None), [fake_pkg, fake_src])

    def test_non_gentoo_authors_copyright_in_gentoo(self):
        """Ebuilds in the gentoo repo must use 'Gentoo Authors'."""
        bad_copyrights = [
            '# Copyright 1999-2019 D. E. Veloper\n',
            '# Copyright 2019 辣鸡汤\n',
        ]
        fake_pkg = self.mk_pkg()
        for line in bad_copyrights:
            fake_src = [line, self.check_kls.license_header]
            r = self.assertReport(self.check_kls(options=None), [fake_pkg, fake_src])
            assert isinstance(r, codingstyle.NonGentooAuthorsCopyright)
            assert line.strip() in str(r)

    def test_license_headers(self):
        copyright = '# Copyright 1999-2019 Gentoo Authors\n'
        fake_pkg = self.mk_pkg()
        fake_src = [copyright, self.check_kls.license_header]
        self.assertNoReport(self.check_kls(options=None), [fake_pkg, fake_src])

        bad_license_headers = [
            '',
            '\n',
            f'{self.check_kls.license_header} ',
            f' {self.check_kls.license_header}',
            '# Distributed under the terms of the GNU General Public License v3'
        ]
        for line in bad_license_headers:
            fake_src = [copyright, line]
            r = self.assertReport(self.check_kls(options=None), [fake_pkg, fake_src])
            assert isinstance(r, codingstyle.InvalidLicenseHeader)
            assert line.strip() in str(r)


class TestHomepageInSrcUri(misc.ReportTestCase):

    check_kls = codingstyle.HomepageInSrcUriCheck

    def mk_pkg(self):
        return misc.FakePkg("dev-util/diffball-0.5")

    def test_single_line(self):
        fake_pkg = self.mk_pkg()
        fake_src = ['HOMEPAGE="https://example.com/"\n',
                    'SRC_URI="${HOMEPAGE}/${P}.tar.bz2"\n']
        r = self.assertReport(self.check_kls(options=None), [fake_pkg, fake_src])
        assert isinstance(r, codingstyle.HomepageInSrcUri)
        assert str(r) == '${HOMEPAGE} in SRC_URI'

    def test_multi_line(self):
        fake_pkg = self.mk_pkg()
        fake_src = ['HOMEPAGE="https://example.com/"\n',
                    'SRC_URI="https://example.org/${P}-manpages.tar.bz2\n',
                    '\t${HOMEPAGE}/${P}.tar.bz2"\n']
        r = self.assertReport(self.check_kls(options=None), [fake_pkg, fake_src])
        assert isinstance(r, codingstyle.HomepageInSrcUri)

    def test_no_match(self):
        fake_pkg = self.mk_pkg()
        fake_src = ['HOMEPAGE="https://example.com/"\n',
                    'SRC_URI="https://example.com/${P}.tar.bz2"\n']
        self.assertNoReport(self.check_kls(options=None), [fake_pkg, fake_src])

    def test_no_false_positive(self):
        fake_pkg = self.mk_pkg()
        fake_src = ['HOMEPAGE="https://example.com/"\n',
                    'SRC_URI="https://example.com/${P}.tar.bz2"\n',
                    '# ${HOMEPAGE} must not be used here\n']
        self.assertNoReport(self.check_kls(options=None), [fake_pkg, fake_src])
