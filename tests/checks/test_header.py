from pkgcheck.checks import header
from snakeoil.cli import arghparse

from .. import misc


class TestEbuildHeaderCheck(misc.ReportTestCase):
    check_kls = header.EbuildHeaderCheck

    def mk_check(self):
        options = arghparse.Namespace(gentoo_repo=True)
        return self.check_kls(options)

    def mk_pkg(self, **kwargs):
        return misc.FakePkg("dev-util/diffball-0.5", **kwargs)

    def test_empty_file(self):
        fake_pkg = self.mk_pkg(lines=())
        self.assertNoReport(self.mk_check(), fake_pkg)

    def test_good_copyright(self):
        good_copyrights = [
            "# Copyright 1999-2019 Gentoo Authors\n",
            "# Copyright 2019 Gentoo Authors\n",
            "# Copyright 2010-2017 Gentoo Authors\n",
        ]
        for line in good_copyrights:
            fake_src = [line, self.check_kls.license_header]
            fake_pkg = self.mk_pkg(lines=fake_src)
            self.assertNoReport(self.mk_check(), fake_pkg)

    def test_invalid_copyright(self):
        bad_copyrights = [
            "# Copyright (c) 1999-2019 Gentoo Authors\n",
            "# Copyright Gentoo Authors\n",
            "# Gentoo Authors\n",
            "# Here is entirely random text\n",
            "\n",
        ]
        for line in bad_copyrights:
            fake_src = [line, self.check_kls.license_header]
            fake_pkg = self.mk_pkg(lines=fake_src)
            r = self.assertReport(self.mk_check(), fake_pkg)
            assert isinstance(r, header.EbuildInvalidCopyright)
            assert line.strip() in str(r)

    def test_new_foundation_copyright(self):
        """Foundation copyright on new ebuilds triggers the report."""
        bad_copyrights = [
            "# Copyright 1999-2019 Gentoo Foundation\n",
            "# Copyright 2019 Gentoo Foundation\n",
            "# Copyright 3125 Gentoo Foundation\n",
            "# Copyright 2010-2021 Gentoo Foundation\n",
        ]
        for line in bad_copyrights:
            fake_src = [line, self.check_kls.license_header]
            fake_pkg = self.mk_pkg(lines=fake_src)
            r = self.assertReport(self.mk_check(), fake_pkg)
            assert isinstance(r, header.EbuildOldGentooCopyright)
            assert line.strip() in str(r)

    def test_old_foundation_copyright(self):
        """Foundation copyright on old ebuilds does not trigger false positives."""
        good_copyrights = [
            "# Copyright 1999-2018 Gentoo Foundation\n",
            "# Copyright 2016 Gentoo Foundation\n",
            "# Copyright 2010-2017 Gentoo Foundation\n",
        ]
        for line in good_copyrights:
            fake_src = [line, self.check_kls.license_header]
            fake_pkg = self.mk_pkg(lines=fake_src)
            self.assertNoReport(self.mk_check(), fake_pkg)

    def test_non_gentoo_authors_copyright_in_gentoo(self):
        """Ebuilds in the gentoo repo must use 'Gentoo Authors'."""
        bad_copyrights = [
            "# Copyright 1999-2019 D. E. Veloper\n",
            "# Copyright 2019 辣鸡汤\n",
        ]
        for line in bad_copyrights:
            fake_src = [line, self.check_kls.license_header]
            fake_pkg = self.mk_pkg(lines=fake_src)
            r = self.assertReport(self.mk_check(), fake_pkg)
            assert isinstance(r, header.EbuildNonGentooAuthorsCopyright)
            assert line.strip() in str(r)

    def test_license_headers(self):
        copyright = "# Copyright 1999-2019 Gentoo Authors\n"
        fake_src = [copyright, self.check_kls.license_header]
        fake_pkg = self.mk_pkg(lines=fake_src)
        self.assertNoReport(self.mk_check(), fake_pkg)

        bad_license_headers = [
            [],
            [""],
            ["\n"],
            [f"{self.check_kls.license_header} "],
            [f" {self.check_kls.license_header}"],
            ["# Distributed under the terms of the GNU General Public License v3"],
        ]
        for content in bad_license_headers:
            fake_src = [copyright] + content
            fake_pkg = self.mk_pkg(lines=fake_src)
            r = self.assertReport(self.mk_check(), fake_pkg)
            assert isinstance(r, header.EbuildInvalidLicenseHeader)
            expected = content[0].strip() if content else "missing license header"
            assert expected in str(r)
