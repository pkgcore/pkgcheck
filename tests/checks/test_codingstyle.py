from itertools import chain

import pytest
from pkgcheck.checks import codingstyle
from pkgcheck.sources import _ParsedPkg
from pkgcore.ebuild.eapi import EAPI

from .. import misc


class TestInsintoCheck(misc.ReportTestCase):

    check_kls = codingstyle.InsintoCheck

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
        absolute = [
            ("/bin/blah", "/bin/baz"),
            ('"/bin/blah baz"', "/bin/blahbaz"),
            ("'/bin/blah baz'", "/bin/blahbaz"),
            ("/etc/Boo", "/etc/boo"),
        ]

        absolute_prefixed = []
        for path_var in codingstyle.PATH_VARIABLES:
            src, dest = ('/bin/blah', '/bin/bash')
            absolute_prefixed.append((f'"${{{path_var}}}"{src}', dest))
            absolute_prefixed.append((f'"${{{path_var}%/}}"{src}', dest))
            src, dest = ('/bin/blah baz', '/bin/blahbaz')
            absolute_prefixed.append((f'"${{{path_var}}}{src}"', dest))
            absolute_prefixed.append((f'"${{{path_var}%/}}{src}"', dest))

        relative = [
            ("blah", "/bin/baz"),
            ('"blah baz"', "/bin/blahbaz"),
            ("Boo", "/etc/boo"),
        ]

        unhandled = [
            ("/crazy/root/dir", "/crazy/symlink"),
        ]

        fake_src = [
            "# This is our first fake ebuild\n",
            "\n",
        ]
        for src, dest in chain.from_iterable((absolute, absolute_prefixed, relative, unhandled)):
            fake_src.append(f"\tdosym {src} {dest}\n")
        fake_src.append("# That's it for now\n")
        fake_pkg = misc.FakePkg("dev-util/diffball-0.5", lines=fake_src)

        check = self.check_kls(None)
        reports = self.assertReports(check, fake_pkg)

        assert len(reports) == len(absolute) + len(absolute_prefixed)
        for r, (src, dest) in zip(reports, absolute + absolute_prefixed):
            assert f'dosym {src}' in str(r)


class TestPathVariablesCheck(misc.ReportTestCase):

    check_kls = codingstyle.PathVariablesCheck
    check = check_kls(None)

    def _found(self, cls, suffix=''):
        # check single and multiple matches across all specified variables
        for lines in (1, 2):
            for path_var in codingstyle.PATH_VARIABLES:
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
        for path_var in codingstyle.PATH_VARIABLES:
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


class TestStaticSrcUri(misc.ReportTestCase):

    check_kls = codingstyle.MetadataVarCheck
    check = check_kls(None)

    @staticmethod
    def _prepare_pkg(uri_value: str, rename: str = '', pkgver: str = 'diffball-0.1.2.3'):
        if rename:
            rename = f' -> {rename}'
        uri = f'https://github.com/pkgcore/pkgcheck/archive/{uri_value}.tar.gz'
        fake_src = [
            f'SRC_URI="{uri}{rename}"\n'
        ]

        fake_pkg = misc.FakePkg(f"dev-util/{pkgver}", ebuild=''.join(fake_src), lines=fake_src)
        data = ''.join(fake_src).encode()
        return _ParsedPkg(data, pkg=fake_pkg)


    @pytest.mark.parametrize('value', (
        '${P}',
        '${PV}',
        'v${PV}',
        'random-0.1.2.3', # not a valid prefix
        '1.2.3', # currently we support only ver_cut with start=1
        '0', # for ver_cut only if more then 1 part
    ))
    def test_no_report(self, value):
        self.assertNoReport(self.check, self._prepare_pkg(value))

    @pytest.mark.parametrize(('value', 'static_str', 'replacement'), (
        ('diffball-0.1.2.3', 'diffball-0.1.2.3', '${P}'),
        ('Diffball-0.1.2.3', 'Diffball-0.1.2.3', '${P^}'),
        ('DIFFBALL-0.1.2.3', 'DIFFBALL-0.1.2.3', '${P^^}'),
        ('diffball-0123', 'diffball-0123', '${P//.}'),
        ('Diffball-0123', 'Diffball-0123', '${P^//.}'),
        ('0.1.2.3', '0.1.2.3', '${PV}'),
        ('v0.1.2.3', '0.1.2.3', '${PV}'),
        ('0.1.2', '0.1.2', '$(ver_cut 1-3)'),
        ('0.1', '0.1', '$(ver_cut 1-2)'),
        ('diffball-0.1.2', '0.1.2', '$(ver_cut 1-3)'),
        ('v0123', '0123', "${PV//.}"),
        ('012.3', '012.3', "$(ver_rs 1-2 '')"),
        ('012.3', '012.3', "$(ver_rs 1-2 '')"),
        ('0_1_2_3', '0_1_2_3', "${PV//./_}"),
        ('0_1_2.3', '0_1_2.3', "$(ver_rs 1-2 '_')"),
        ('0-1.2.3', '0-1.2.3', "$(ver_rs 1 '-')"),
    ))
    def test_with_report(self, value, static_str, replacement):
        r = self.assertReport(self.check, self._prepare_pkg(value))
        assert r.static_str == static_str
        assert r.replacement == replacement

    def test_rename(self):
        self.assertNoReport(self.check, self._prepare_pkg('${P}', '${P}.tar.gz'))

        r = self.assertReport(self.check, self._prepare_pkg('${P}', 'diffball-0.1.2.3.tar.gz'))
        assert r.static_str == 'diffball-0.1.2.3'
        assert r.replacement == '${P}'

        r = self.assertReport(self.check, self._prepare_pkg('0.1.2.3', '${P}.tar.gz'))
        assert r.static_str == '0.1.2.3'
        assert r.replacement == '${PV}'

        r = self.assertReport(self.check, self._prepare_pkg('diffball-0.1.2.3', 'diffball-0.1.2.3.tar.gz'))
        assert r.static_str == 'diffball-0.1.2.3'
        assert r.replacement == '${P}'

    def test_capitalize(self):
        r = self.assertReport(self.check, self._prepare_pkg('DIFFBALL-0.1.2.3', pkgver='DIFFBALL-0.1.2.3'))
        assert r.static_str == 'DIFFBALL-0.1.2.3'
        assert r.replacement == '${P}'

        r = self.assertReport(self.check, self._prepare_pkg('Diffball-0.1.2.3', pkgver='Diffball-0.1.2.3'))
        assert r.static_str == 'Diffball-0.1.2.3'
        assert r.replacement == '${P}'
