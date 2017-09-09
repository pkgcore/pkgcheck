import os
import tempfile

from snakeoil import fileutils
from snakeoil.osutils import pjoin
from snakeoil.test.mixins import TempDirMixin

from pkgcheck import pkgdir_checks
from pkgcheck.test import misc


class PkgDirReportTest(TempDirMixin, misc.ReportTestCase):
    """Various FILESDIR related test support."""

    check_kls = pkgdir_checks.PkgDirReport

    def setUp(self):
        TempDirMixin.setUp(self)
        self.check = pkgdir_checks.PkgDirReport(None, None)

    def tearDown(self):
        TempDirMixin.tearDown(self)

    def mk_pkg(self, files={}):
        return misc.FakeFilesDirPkg(
            "dev-util/diffball-0.7.1",
            self.get_pkgdir_with_filesdir(files))

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


class TestDuplicateFilesReport(PkgDirReportTest):
    """Check DuplicateFiles results."""

    def test_it(self):
        # empty filesdir
        self.assertNoReport(self.check, [self.mk_pkg()])

        # filesdir with two unique files
        self.assertNoReport(self.check, [self.mk_pkg({'test': 'abc', 'test2': 'bcd'})])

        # filesdir with a duplicate
        r = self.assertIsInstance(
            self.assertReport(self.check, [self.mk_pkg({'test': 'abc', 'test2': 'abc'})]),
            pkgdir_checks.DuplicateFiles)
        self.assertEqual(r.files, ('files/test', 'files/test2'))
        self.assertEqual(r.files, ('files/test', 'files/test2'))

        # two sets of duplicates and one unique
        r = self.assertReports(self.check, [self.mk_pkg(
            {'test': 'abc', 'test2': 'abc', 'test3': 'bcd', 'test4': 'bcd', 'test5': 'zzz'})])
        self.assertLen(r, 2)
        self.assertIsInstance(r[0], pkgdir_checks.DuplicateFiles)
        self.assertIsInstance(r[1], pkgdir_checks.DuplicateFiles)
        self.assertEqual(
            tuple(sorted(x.files for x in r)),
            (('files/test', 'files/test2'), ('files/test3', 'files/test4'))
        )


class TestEmptyFileReport(PkgDirReportTest):
    """Check EmptyFile results."""

    def test_it(self):
        # empty filesdir
        self.assertNoReport(self.check, [self.mk_pkg()])

        # filesdir with an empty file
        self.assertIsInstance(
            self.assertReport(self.check, [self.mk_pkg({'test': ''})]),
            pkgdir_checks.EmptyFile)

        # filesdir with a non-empty file
        self.assertNoReport(self.check, [self.mk_pkg({'test': 'asdfgh'})])

        # a mix of both
        r = self.assertIsInstance(
            self.assertReport(self.check, [self.mk_pkg({'test': 'asdfgh', 'test2': ''})]),
            pkgdir_checks.EmptyFile)
        self.assertEqual(r.filename, 'files/test2')
        r = self.assertIsInstance(
            self.assertReport(self.check, [self.mk_pkg({'test': '', 'test2': 'asdfgh'})]),
            pkgdir_checks.EmptyFile)
        self.assertEqual(r.filename, 'files/test')

        # two empty files
        r = self.assertReports(self.check, [self.mk_pkg({'test': '', 'test2': ''})])
        self.assertLen(r, 2)
        self.assertIsInstance(r[0], pkgdir_checks.EmptyFile)
        self.assertIsInstance(r[1], pkgdir_checks.EmptyFile)
        self.assertEqual(sorted(x.filename for x in r), ['files/test', 'files/test2'])
