import os
import tempfile

from snakeoil import fileutils
from snakeoil.osutils import pjoin
from snakeoil.test.mixins import TempDirMixin

from pkgcheck import pkgdir_checks
from pkgcheck.test import misc


class filesdir_mixin(TempDirMixin):
    """Various FILESDIR related test support."""

    def get_pkgdir_with_filesdir(self, files={}):
        """Create a temporary directory for the ebuild with files/ subdirectory.

        Fill it in with files from the files dict (key specifying the filename,
        value the contents).
        """
        ebuild_base = tempfile.mkdtemp(dir=self.dir)
        base = pjoin(ebuild_base, 'files')
        os.mkdir(base)
        for fn, contents in files.iteritems():
            fileutils.write_file(pjoin(base, fn), 'w', contents)
        return ebuild_base


class TestEmptyFileReport(filesdir_mixin, misc.ReportTestCase):

    check_kls = pkgdir_checks.PkgDirReport

    def mk_pkg(self, files={}):
        return misc.FakeFilesDirPkg(
            "dev-util/diffball-0.7.1",
            self.get_pkgdir_with_filesdir(files))

    def test_it(self):
        check = pkgdir_checks.PkgDirReport(None, None)

        # empty filesdir
        self.assertNoReport(check, [self.mk_pkg()])

        # filesdir with an empty file
        self.assertIsInstance(
            self.assertReport(check, [self.mk_pkg({'test': ''})]),
            pkgdir_checks.EmptyFile)

        # filesdir with a non-empty file
        self.assertNoReport(check, [self.mk_pkg({'test': 'asdfgh'})])

        # a mix of both
        self.assertIsInstance(
            self.assertReport(check, [self.mk_pkg({'test': 'asdfgh', 'test2': ''})]),
            pkgdir_checks.EmptyFile)
        self.assertIsInstance(
            self.assertReport(check, [self.mk_pkg({'test': '', 'test2': 'asdfgh'})]),
            pkgdir_checks.EmptyFile)

        # two empty files
        r = self.assertReports(check, [self.mk_pkg({'test': '', 'test2': ''})])
        self.assertLen(r, 2)
        self.assertIsInstance(r[0], pkgdir_checks.EmptyFile)
        self.assertIsInstance(r[1], pkgdir_checks.EmptyFile)
