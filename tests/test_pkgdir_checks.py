import os
import tempfile
import uuid

from pkgcore.test.misc import FakeRepo
from snakeoil import fileutils
from snakeoil.fileutils import touch
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

    def mk_pkg(self, files={}, pkg=None):
        if pkg is None:
            # generate random cat/PN
            category = uuid.uuid4().hex
            PN = uuid.uuid4().hex
        else:
            category, PN = pkg.split(os.path.sep)

        pkg = f"{category}/{PN}-0.7.1"
        repo = FakeRepo(repo_id='repo', location=self.dir)
        self.filesdir = pjoin(repo.location, category, PN, 'files')
        os.makedirs(self.filesdir)

        # create specified files in FILESDIR
        for fn, contents in files.items():
            fileutils.write_file(pjoin(self.filesdir, fn), 'w', contents)

        return misc.FakeFilesDirPkg(pkg, repo=repo)

    def test_it(self):
        # no files
        self.assertNoReport(self.check, [self.mk_pkg()])


class TestDuplicateFilesReport(PkgDirReportTest):
    """Check DuplicateFiles results."""

    def test_it(self):
        # filesdir with two unique files
        self.assertNoReport(self.check, [self.mk_pkg({'test': 'abc', 'test2': 'bcd'})])

        # filesdir with a duplicate
        r = self.assertReport(self.check, [self.mk_pkg({'test': 'abc', 'test2': 'abc'})])
        self.assertIsInstance(r, pkgdir_checks.DuplicateFiles)
        assert r.files == ('files/test', 'files/test2')
        assert r.files == ('files/test', 'files/test2')

        # two sets of duplicates and one unique
        r = self.assertReports(self.check, [self.mk_pkg(
            {'test': 'abc', 'test2': 'abc', 'test3': 'bcd', 'test4': 'bcd', 'test5': 'zzz'})])
        assert len(r) == 2
        self.assertIsInstance(r[0], pkgdir_checks.DuplicateFiles)
        self.assertIsInstance(r[1], pkgdir_checks.DuplicateFiles)
        assert (
            tuple(sorted(x.files for x in r)) ==
            (('files/test', 'files/test2'), ('files/test3', 'files/test4'))
        )


class TestEmptyFileReport(PkgDirReportTest):
    """Check EmptyFile results."""

    def test_it(self):
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
        assert r.filename == 'files/test2'
        r = self.assertIsInstance(
            self.assertReport(self.check, [self.mk_pkg({'test': '', 'test2': 'asdfgh'})]),
            pkgdir_checks.EmptyFile)
        assert r.filename == 'files/test'

        # two empty files
        r = self.assertReports(self.check, [self.mk_pkg({'test': '', 'test2': ''})])
        assert len(r) == 2
        self.assertIsInstance(r[0], pkgdir_checks.EmptyFile)
        self.assertIsInstance(r[1], pkgdir_checks.EmptyFile)
        assert sorted(x.filename for x in r) == ['files/test', 'files/test2']


class TestMismatchedPN(PkgDirReportTest):
    """Check MismatchedPN results."""

    def test_it(self):
        # multiple regular ebuilds
        pkg = self.mk_pkg()
        touch(pjoin(os.path.dirname(pkg.path), f'{pkg.package}-0.ebuild'))
        touch(pjoin(os.path.dirname(pkg.path), f'{pkg.package}-1.ebuild'))
        touch(pjoin(os.path.dirname(pkg.path), f'{pkg.package}-2.ebuild'))
        self.assertNoReport(self.check, [pkg])

        # single, mismatched ebuild
        pkg = self.mk_pkg()
        touch(pjoin(os.path.dirname(pkg.path), 'mismatched-0.ebuild'))
        r = self.assertReport(self.check, [pkg])
        self.assertIsInstance(r, pkgdir_checks.MismatchedPN)
        assert r.ebuilds == ('mismatched-0',)

        # multiple ebuilds, multiple mismatched
        pkg = self.mk_pkg()
        touch(pjoin(os.path.dirname(pkg.path), f'{pkg.package}-0.ebuild'))
        touch(pjoin(os.path.dirname(pkg.path), f'{pkg.package}-1.ebuild'))
        touch(pjoin(os.path.dirname(pkg.path), 'mismatched-0.ebuild'))
        touch(pjoin(os.path.dirname(pkg.path), 'abc-1.ebuild'))
        r = self.assertReport(self.check, [pkg])
        self.assertIsInstance(r, pkgdir_checks.MismatchedPN)
        assert r.ebuilds == ('abc-1', 'mismatched-0')


class TestInvalidPN(PkgDirReportTest):
    """Check InvalidPN results."""

    def test_it(self):
        # regular ebuild
        pkg = self.mk_pkg()
        touch(pjoin(os.path.dirname(pkg.path), f'{pkg.package}-0.ebuild'))
        self.assertNoReport(self.check, [pkg])

        # single, invalid ebuild
        pkg = self.mk_pkg(pkg='sys-apps/invalid')
        touch(pjoin(os.path.dirname(pkg.path), 'invalid-0-foo.ebuild'))
        r = self.assertReport(self.check, [pkg])
        self.assertIsInstance(r, pkgdir_checks.InvalidPN)
        assert r.ebuilds == ('invalid-0-foo',)

        # multiple ebuilds, multiple invalid
        pkg = self.mk_pkg(pkg='sys-apps/bar')
        touch(pjoin(os.path.dirname(pkg.path), 'bar-0.ebuild'))
        touch(pjoin(os.path.dirname(pkg.path), 'bar-1.ebuild'))
        touch(pjoin(os.path.dirname(pkg.path), 'bar-0-foo1.ebuild'))
        touch(pjoin(os.path.dirname(pkg.path), 'bar-1-foo2.ebuild'))
        r = self.assertReport(self.check, [pkg])
        self.assertIsInstance(r, pkgdir_checks.InvalidPN)
        assert r.ebuilds == ('bar-0-foo1', 'bar-1-foo2')


class TestSizeViolation(PkgDirReportTest):
    """Check SizeViolation results."""

    def test_it(self):
        # files under the 20k limit
        pkg = self.mk_pkg()
        for name, size in (('small', 1024*10),
                           ('limit', 1024*20-1)):
            with open(pjoin(self.filesdir, name), 'w') as f:
                f.seek(size)
                f.write('\0')
        self.assertNoReport(self.check, [pkg])

        # single file one byte over the 20k limit
        pkg = self.mk_pkg()
        with open(pjoin(self.filesdir, 'over'), 'w') as f:
            f.seek(1024*20)
            f.write('\0')
        r = self.assertReport(self.check, [pkg])
        self.assertIsInstance(r, pkgdir_checks.SizeViolation)
        assert r.filename == 'files/over'
        assert r.size == 1024*20+1

        # mix of files
        pkg = self.mk_pkg()
        for name, size in (('small', 1024*10),
                           ('limit', 1024*20-1),
                           ('over', 1024*20),
                           ('massive', 1024*100)):
            with open(pjoin(self.filesdir, name), 'w') as f:
                f.seek(size)
                f.write('\0')
        r = self.assertReports(self.check, [pkg])
        assert len(r) == 2
        self.assertIsInstance(r[0], pkgdir_checks.SizeViolation)
        self.assertIsInstance(r[1], pkgdir_checks.SizeViolation)
        assert (
            tuple(sorted((x.filename, x.size) for x in r)) ==
            (('files/massive', 1024*100+1), ('files/over', 1024*20+1))
        )


class TestExecutableFile(PkgDirReportTest):
    """Check ExecutableFile results."""

    def test_it(self):
        # non-empty filesdir
        self.assertNoReport(self.check, [self.mk_pkg({'test': 'asdfgh'})])

        # executable ebuild
        pkg = self.mk_pkg()
        touch(pkg.path, mode=0o777)
        r = self.assertReport(self.check, [pkg])
        self.assertIsInstance(r, pkgdir_checks.ExecutableFile)
        assert r.filename == os.path.basename(pkg.path)

        # executable Manifest and metadata
        pkg = self.mk_pkg()
        touch(pjoin(os.path.dirname(pkg.path), 'Manifest'), mode=0o755)
        touch(pjoin(os.path.dirname(pkg.path), 'metadata.xml'), mode=0o744)
        r = self.assertReports(self.check, [pkg])
        assert len(r) == 2
        self.assertIsInstance(r[0], pkgdir_checks.ExecutableFile)
        self.assertIsInstance(r[1], pkgdir_checks.ExecutableFile)
        assert (
            tuple(sorted(x.filename for x in r)) ==
            ('Manifest', 'metadata.xml')
        )

        # mix of regular files and executable FILESDIR file
        pkg = self.mk_pkg({'foo.init': 'blah'})
        touch(pkg.path)
        touch(pjoin(os.path.dirname(pkg.path), 'Manifest'))
        touch(pjoin(os.path.dirname(pkg.path), 'metadata.xml'))
        os.chmod(pjoin(os.path.dirname(pkg.path), 'files', 'foo.init'), 0o645)
        r = self.assertReport(self.check, [pkg])
        self.assertIsInstance(r, pkgdir_checks.ExecutableFile)
        assert r.filename == 'files/foo.init'
