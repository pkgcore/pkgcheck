import os
from datetime import datetime, timedelta

import pytest
from pkgcheck import addons
from pkgcheck.checks import SkipCheck, pkgdir
from pkgcore.ebuild.cpv import UnversionedCPV
from pkgcore.test.misc import FakeRepo
from snakeoil import fileutils
from snakeoil.cli import arghparse
from snakeoil.fileutils import touch
from snakeoil.osutils import ensure_dirs, pjoin

from .. import misc


class PkgDirCheckBase(misc.ReportTestCase):
    """Various FILESDIR related test support."""

    check_kls = pkgdir.PkgDirCheck

    @pytest.fixture(autouse=True)
    def _create_repo(self, tmpdir):
        self.repo = FakeRepo(repo_id='repo', location=str(tmpdir))

    def mk_check(self, gentoo=False):
        options = arghparse.Namespace(
            target_repo=self.repo, cache={'git': False}, gentoo_repo=gentoo)
        kwargs = {}
        if addons.git.GitAddon in self.check_kls.required_addons:
            kwargs['git_addon'] = addons.git.GitAddon(options)
        return self.check_kls(options, **kwargs)

    def mk_pkg(self, files={}, category=None, package=None, version='0.7.1', revision=''):
        # generate random cat/PN
        category = misc.random_str() if category is None else category
        package = misc.random_str() if package is None else package

        pkg = f"{category}/{package}-{version}{revision}"
        self.filesdir = pjoin(self.repo.location, category, package, 'files')
        # create files dir with random empty subdir
        os.makedirs(pjoin(self.filesdir, misc.random_str()), exist_ok=True)

        # create dirs that should be ignored
        for d in getattr(self.check_kls, 'ignore_dirs', ()):
            os.makedirs(pjoin(self.filesdir, d), exist_ok=True)

        # create specified files in FILESDIR
        for fn, contents in files.items():
            with open(pjoin(self.filesdir, fn), 'w') as file:
                file.write(contents)

        return misc.FakeFilesDirPkg(pkg, repo=self.repo)


class TestPkgDirCheck(PkgDirCheckBase):
    """Base tests for the PkgDirCheck."""

    def test_empty_dir(self):
        self.assertNoReport(self.mk_check(), [self.mk_pkg()])


class TestDuplicateFiles(PkgDirCheckBase):
    """Check DuplicateFiles results."""

    def test_unique_files(self):
        self.assertNoReport(self.mk_check(), [self.mk_pkg({'test': 'abc', 'test2': 'bcd'})])

    def test_single_duplicate(self):
        pkg = self.mk_pkg({'test': 'abc', 'test2': 'abc'})
        r = self.assertReport(self.mk_check(), [pkg])
        assert isinstance(r, pkgdir.DuplicateFiles)
        assert r.files == ('files/test', 'files/test2')
        assert "'files/test', 'files/test2'" in str(r)

    def test_multiple_duplicates(self):
        r = self.assertReports(self.mk_check(), [self.mk_pkg(
            {'test': 'abc', 'test2': 'abc', 'test3': 'bcd', 'test4': 'bcd', 'test5': 'zzz'})])
        assert len(r) == 2
        assert isinstance(r[0], pkgdir.DuplicateFiles)
        assert isinstance(r[1], pkgdir.DuplicateFiles)
        assert (
            tuple(sorted(x.files for x in r)) ==
            (('files/test', 'files/test2'), ('files/test3', 'files/test4'))
        )


class TestEmptyFile(PkgDirCheckBase):
    """Check EmptyFile results."""

    def test_nonempty_file(self):
        self.assertNoReport(self.mk_check(), [self.mk_pkg({'test': 'asdfgh'})])

    def test_single_empty_file(self):
        assert isinstance(
            self.assertReport(self.mk_check(), [self.mk_pkg({'test': ''})]),
            pkgdir.EmptyFile)

    def test_multiple_empty_files(self):
        r = self.assertReports(self.mk_check(), [self.mk_pkg({'test': '', 'test2': ''})])
        assert len(r) == 2
        assert isinstance(r[0], pkgdir.EmptyFile)
        assert isinstance(r[1], pkgdir.EmptyFile)
        assert sorted(x.filename for x in r) == ['files/test', 'files/test2']

    def test_mixture_of_files(self):
        r = self.assertReport(self.mk_check(), [self.mk_pkg({'test': 'asdfgh', 'test2': ''})])
        assert isinstance(r, pkgdir.EmptyFile)
        assert r.filename == 'files/test2'
        assert 'files/test2' in str(r)
        r = self.assertReport(self.mk_check(), [self.mk_pkg({'test': '', 'test2': 'asdfgh'})])
        assert isinstance(r, pkgdir.EmptyFile)
        assert r.filename == 'files/test'
        assert 'files/test' in str(r)


class TestMismatchedPN(PkgDirCheckBase):
    """Check MismatchedPN results."""

    def test_multiple_regular_ebuilds(self):
        pkg = self.mk_pkg()
        touch(pjoin(os.path.dirname(pkg.path), f'{pkg.package}-0.ebuild'))
        touch(pjoin(os.path.dirname(pkg.path), f'{pkg.package}-1.ebuild'))
        touch(pjoin(os.path.dirname(pkg.path), f'{pkg.package}-2.ebuild'))
        self.assertNoReport(self.mk_check(), [pkg])

    def test_single_mismatched_ebuild(self):
        pkg = self.mk_pkg()
        touch(pjoin(os.path.dirname(pkg.path), 'mismatched-0.ebuild'))
        r = self.assertReport(self.mk_check(), [pkg])
        assert isinstance(r, pkgdir.MismatchedPN)
        assert r.ebuilds == ('mismatched-0',)
        assert 'mismatched-0' in str(r)

    def test_multiple_mismatched_ebuilds(self):
        pkg = self.mk_pkg()
        touch(pjoin(os.path.dirname(pkg.path), f'{pkg.package}-0.ebuild'))
        touch(pjoin(os.path.dirname(pkg.path), f'{pkg.package}-1.ebuild'))
        touch(pjoin(os.path.dirname(pkg.path), 'mismatched-0.ebuild'))
        touch(pjoin(os.path.dirname(pkg.path), 'abc-1.ebuild'))
        r = self.assertReport(self.mk_check(), [pkg])
        assert isinstance(r, pkgdir.MismatchedPN)
        assert r.ebuilds == ('abc-1', 'mismatched-0')
        assert 'abc-1, mismatched-0' in str(r)


class TestInvalidPN(PkgDirCheckBase):
    """Check InvalidPN results."""

    def test_regular_ebuild(self):
        pkg = self.mk_pkg()
        touch(pjoin(os.path.dirname(pkg.path), f'{pkg.package}-0.ebuild'))
        self.assertNoReport(self.mk_check(), [pkg])

    def test_single_invalid_ebuild(self):
        pkg = self.mk_pkg(category='sys-apps', package='invalid')
        touch(pjoin(os.path.dirname(pkg.path), 'invalid-0-foo.ebuild'))
        r = self.assertReport(self.mk_check(), [pkg])
        assert isinstance(r, pkgdir.InvalidPN)
        assert r.ebuilds == ('invalid-0-foo',)
        assert 'invalid-0-foo' in str(r)

    def test_multiple_invalid_ebuilds(self):
        pkg = self.mk_pkg(category='sys-apps', package='bar')
        touch(pjoin(os.path.dirname(pkg.path), 'bar-0.ebuild'))
        touch(pjoin(os.path.dirname(pkg.path), 'bar-1.ebuild'))
        touch(pjoin(os.path.dirname(pkg.path), 'bar-0-foo1.ebuild'))
        touch(pjoin(os.path.dirname(pkg.path), 'bar-1-foo2.ebuild'))
        r = self.assertReport(self.mk_check(), [pkg])
        assert isinstance(r, pkgdir.InvalidPN)
        assert r.ebuilds == ('bar-0-foo1', 'bar-1-foo2')
        assert 'bar-0-foo1, bar-1-foo2' in str(r)


class TestInvalidUTF8(PkgDirCheckBase):
    """Check InvalidUTF8 results."""

    def test_ascii_ebuild(self):
        pkg = self.mk_pkg()
        ebuild_path = pjoin(os.path.dirname(pkg.path), f'{pkg.package}-0.ebuild')
        with open(ebuild_path, 'w', encoding='ascii') as f:
            f.write('EAPI=7\nDESCRIPTION="foobar"\n')
        self.assertNoReport(self.mk_check(), [pkg])

    def test_utf8_ebuild(self):
        pkg = self.mk_pkg()
        ebuild_path = pjoin(os.path.dirname(pkg.path), f'{pkg.package}-0.ebuild')
        with open(ebuild_path, 'w') as f:
            f.write('EAPI=6\nDESCRIPTION="fóóbár"\n')
        self.assertNoReport(self.mk_check(), [pkg])

    def test_latin1_ebuild(self):
        pkg = self.mk_pkg()
        ebuild_path = pjoin(os.path.dirname(pkg.path), f'{pkg.package}-0.ebuild')
        with open(ebuild_path, 'w', encoding='latin-1') as f:
            f.write('EAPI=5\nDESCRIPTION="fôòbår"\n')
        r = self.assertReport(self.mk_check(), [pkg])
        assert isinstance(r, pkgdir.InvalidUTF8)
        assert r.filename == f'{pkg.package}-0.ebuild'
        assert r.filename in str(r)


class TestEqualVersions(PkgDirCheckBase):
    """Check EqualVersions results."""

    check_kls = pkgdir.EqualVersionsCheck

    def test_it(self):
        # pkg with no revision
        pkg_a = self.mk_pkg(version='0')
        self.assertNoReport(self.mk_check(), [pkg_a])

        # single, matching revision
        pkg_b = self.mk_pkg(
            category=pkg_a.category, package=pkg_a.package, version='0', revision='-r0')
        r = self.assertReport(self.mk_check(), [pkg_a, pkg_b])
        assert isinstance(r, pkgdir.EqualVersions)
        assert r.versions == ('0', '0-r0')
        assert '[ 0, 0-r0 ]' in str(r)

        # multiple, matching revisions
        pkg_c = self.mk_pkg(
            category=pkg_a.category, package=pkg_a.package, version='0', revision='-r000')
        r = self.assertReport(self.mk_check(), [pkg_a, pkg_b, pkg_c])
        assert isinstance(r, pkgdir.EqualVersions)
        assert r.versions == ('0', '0-r0', '0-r000')
        assert '[ 0, 0-r0, 0-r000 ]' in str(r)

        # unsorted, matching revisions
        pkg_new_version = self.mk_pkg(
            category=pkg_a.category, package=pkg_a.package, version='1')
        r = self.assertReport(self.mk_check(), [pkg_b, pkg_new_version, pkg_c, pkg_a])
        assert isinstance(r, pkgdir.EqualVersions)
        assert r.versions == ('0', '0-r0', '0-r000')
        assert '[ 0, 0-r0, 0-r000 ]' in str(r)

        # multiple, matching revisions with 0 prefixes
        pkg_d = self.mk_pkg(
            category=pkg_a.category, package=pkg_a.package, version='0', revision='-r1')
        pkg_e = self.mk_pkg(
            category=pkg_a.category, package=pkg_a.package, version='0', revision='-r01')
        pkg_f = self.mk_pkg(
            category=pkg_a.category, package=pkg_a.package, version='0', revision='-r001')
        r = self.assertReport(self.mk_check(), [pkg_d, pkg_e, pkg_f])
        assert isinstance(r, pkgdir.EqualVersions)
        assert r.versions == ('0-r001', '0-r01', '0-r1')
        assert '[ 0-r001, 0-r01, 0-r1 ]' in str(r)


class TestSizeViolation(PkgDirCheckBase):
    """Check SizeViolation results."""

    def test_files_under_size_limit(self):
        pkg = self.mk_pkg()
        for name, size in (('small', 1024*10),
                           ('limit', 1024*20-1)):
            with open(pjoin(self.filesdir, name), 'w') as f:
                f.seek(size)
                f.write('\0')
        self.assertNoReport(self.mk_check(), [pkg])

    def test_single_file_over_limit(self):
        pkg = self.mk_pkg()
        with open(pjoin(self.filesdir, 'over'), 'w') as f:
            f.seek(1024*20)
            f.write('\0')
        r = self.assertReport(self.mk_check(), [pkg])
        assert isinstance(r, pkgdir.SizeViolation)
        assert r.filename == 'files/over'
        assert r.size == 1024*20+1
        assert 'files/over' in str(r)

    def test_multiple_files_over_limit(self):
        pkg = self.mk_pkg()
        for name, size in (('small', 1024*10),
                           ('limit', 1024*20-1),
                           ('over', 1024*20),
                           ('massive', 1024*100)):
            with open(pjoin(self.filesdir, name), 'w') as f:
                f.seek(size)
                f.write('\0')
        r = self.assertReports(self.mk_check(), [pkg])
        assert len(r) == 3
        assert isinstance(r[0], pkgdir.SizeViolation)
        assert isinstance(r[1], pkgdir.SizeViolation)
        assert isinstance(r[2], pkgdir.TotalSizeViolation)
        assert (
            tuple(sorted((x.filename, x.size) for x in r[:2])) ==
            (('files/massive', 1024*100+1), ('files/over', 1024*20+1))
        )
        assert r[2].size == 1024*(10+20+20+100)+4-1


class TestExecutableFile(PkgDirCheckBase):
    """Check ExecutableFile results."""

    def test_non_empty_filesdir(self):
        self.assertNoReport(self.mk_check(), [self.mk_pkg({'test': 'asdfgh'})])

    def test_executable_ebuild(self):
        pkg = self.mk_pkg()
        touch(pkg.path, mode=0o777)
        r = self.assertReport(self.mk_check(), [pkg])
        assert isinstance(r, pkgdir.ExecutableFile)
        assert r.filename == os.path.basename(pkg.path)
        assert os.path.basename(pkg.path) in str(r)

    def test_executable_manifest_and_metadata(self):
        pkg = self.mk_pkg()
        touch(pjoin(os.path.dirname(pkg.path), 'Manifest'), mode=0o755)
        touch(pjoin(os.path.dirname(pkg.path), 'metadata.xml'), mode=0o744)
        r = self.assertReports(self.mk_check(), [pkg])
        assert len(r) == 2
        assert isinstance(r[0], pkgdir.ExecutableFile)
        assert isinstance(r[1], pkgdir.ExecutableFile)
        assert (
            tuple(sorted(x.filename for x in r)) ==
            ('Manifest', 'metadata.xml')
        )

    def test_executable_filesdir_file(self):
        pkg = self.mk_pkg({'foo.init': 'blah'})
        touch(pkg.path)
        touch(pjoin(os.path.dirname(pkg.path), 'Manifest'))
        touch(pjoin(os.path.dirname(pkg.path), 'metadata.xml'))
        os.chmod(pjoin(os.path.dirname(pkg.path), 'files', 'foo.init'), 0o645)
        r = self.assertReport(self.mk_check(), [pkg])
        assert isinstance(r, pkgdir.ExecutableFile)
        assert r.filename == 'files/foo.init'
        assert 'files/foo.init' in str(r)


class TestBannedCharacter(PkgDirCheckBase):
    """Check BannedCharacter results."""

    def test_regular_files(self):
        pkg = self.mk_pkg({'foo.init': 'blah'})
        touch(pjoin(os.path.dirname(pkg.path), 'Manifest'))
        touch(pjoin(os.path.dirname(pkg.path), 'metadata.xml'))
        self.assertNoReport(self.mk_check(), [pkg])

    def test_filenames_outside_allowed_charsets(self):
        pkg = self.mk_pkg({
            'foo.init': 'bar',
            'foo.init~': 'foo',
        })
        # vim backup files are flagged by default
        r = self.assertReport(self.mk_check(), [pkg])
        assert isinstance(r, pkgdir.BannedCharacter)
        assert 'files/foo.init~' in str(r)

        # but results are suppressed if a matching git ignore entry exists
        for ignore_file in ('.gitignore', '.git/info/exclude'):
            path = pjoin(self.repo.location, ignore_file)
            ensure_dirs(os.path.dirname(path))
            with open(path, 'w') as f:
                f.write('*~')
            self.assertNoReport(self.mk_check(), [pkg])
            os.unlink(path)


class TestUnknownPkgDirEntry(PkgDirCheckBase):
    """Check UnknownPkgDirEntry results."""

    def test_regular_files(self):
        pkg = self.mk_pkg({'foo.init': 'blah'})
        touch(pjoin(os.path.dirname(pkg.path), 'Manifest'))
        touch(pjoin(os.path.dirname(pkg.path), 'metadata.xml'))
        self.assertNoReport(self.mk_check(), [pkg])

    def test_unknown_non_gentoo_repo(self):
        pkg = self.mk_pkg({'foo.init': 'blah'})
        touch(pjoin(os.path.dirname(pkg.path), 'Manifest'))
        touch(pjoin(os.path.dirname(pkg.path), 'metadata.xml'))
        touch(pjoin(os.path.dirname(pkg.path), 'foo-2'))
        self.assertNoReport(self.mk_check(), [pkg])

    def test_unknown_gentoo_repo(self):
        pkg = self.mk_pkg({'foo.init': 'blah'})
        touch(pjoin(os.path.dirname(pkg.path), 'Manifest'))
        touch(pjoin(os.path.dirname(pkg.path), 'metadata.xml'))
        touch(pjoin(os.path.dirname(pkg.path), 'foo-2'))
        r = self.assertReport(self.mk_check(gentoo=True), [pkg])
        assert isinstance(r, pkgdir.UnknownPkgDirEntry)
        assert 'foo-2' in str(r)

    def test_unknown_gitignore(self):
        pkg = self.mk_pkg(files={'foo.init': 'blah'}, category='dev-util', package='foo')
        touch(pjoin(os.path.dirname(pkg.path), 'Manifest'))
        touch(pjoin(os.path.dirname(pkg.path), 'metadata.xml'))
        touch(pjoin(os.path.dirname(pkg.path), 'foo-0.ebuild'))
        touch(pjoin(os.path.dirname(pkg.path), 'foo-0.ebuild.swp'))
        r = self.assertReport(self.mk_check(gentoo=True), [pkg])
        assert isinstance(r, pkgdir.UnknownPkgDirEntry)
        assert 'foo-0.ebuild.swp' in str(r)

        # results are suppressed if a matching .gitignore entry exists
        with open(pjoin(self.repo.location, '.gitignore'), 'w') as f:
            f.write('*.swp')
        self.assertNoReport(self.mk_check(gentoo=True), [pkg])


class TestLiveOnlyCheck(misc.ReportTestCase):

    check_kls = pkgdir.LiveOnlyCheck

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, tool, make_repo, make_git_repo):
        self._tool = tool
        self.cache_dir = str(tmp_path)

        # initialize parent repo
        self.parent_git_repo = make_git_repo()
        self.parent_repo = make_repo(self.parent_git_repo.path, repo_id='gentoo')
        self.parent_git_repo.add_all('initial commit')
        # create a stub pkg and commit it
        self.parent_repo.create_ebuild('cat/pkg-0', properties='live')
        self.parent_git_repo.add_all('cat/pkg-0')

        # initialize child repo
        self.child_git_repo = make_git_repo()
        self.child_git_repo.run(['git', 'remote', 'add', 'origin', self.parent_git_repo.path])
        self.child_git_repo.run(['git', 'pull', 'origin', 'main'])
        self.child_git_repo.run(['git', 'remote', 'set-head', 'origin', 'main'])
        self.child_repo = make_repo(self.child_git_repo.path)

    def init_check(self, options=None, future=0):
        self.options = options if options is not None else self._options()
        self.check, required_addons, self.source = misc.init_check(self.check_kls, self.options)
        for k, v in required_addons.items():
            setattr(self, k, v)
        if future:
            self.check.today = datetime.today() + timedelta(days=+future)

    def _options(self, **kwargs):
        args = [
            'scan', '-q', '--cache-dir', self.cache_dir,
            '--repo', self.child_repo.location,
        ]
        options, _ = self._tool.parse_args(args)
        return options

    def test_no_git_support(self):
        options = self._options()
        options.cache['git'] = False
        with pytest.raises(SkipCheck, match='git cache support required'):
            self.init_check(options)

    def test_keywords_exist(self):
        self.parent_repo.create_ebuild('cat/pkg-1', keywords=['~amd64'])
        self.parent_git_repo.add_all('cat/pkg-1')
        self.child_git_repo.run(['git', 'pull', 'origin', 'main'])
        self.init_check()
        self.assertNoReport(self.check, self.source)

    def test_all_live_pkgs(self):
        self.parent_repo.create_ebuild('cat/pkg-1', properties='live')
        self.parent_git_repo.add_all('cat/pkg-1')
        self.child_git_repo.run(['git', 'pull', 'origin', 'main'])
        self.init_check()
        # result will trigger for any package age
        expected = pkgdir.LiveOnlyPackage(0, pkg=UnversionedCPV('cat/pkg'))
        r = self.assertReport(self.check, self.source)
        assert r == expected

        # packages are now a year old
        self.init_check(future=365)
        expected = pkgdir.LiveOnlyPackage(365, pkg=UnversionedCPV('cat/pkg'))
        r = self.assertReport(self.check, self.source)
        assert r == expected

    def test_uncommitted_local_ebuild(self):
        self.parent_repo.create_ebuild('cat/pkg-1', properties='live')
        self.parent_git_repo.add_all('cat/pkg-1')
        self.child_git_repo.run(['git', 'pull', 'origin', 'main'])
        self.child_repo.create_ebuild('cat/pkg-2', properties='live')
        self.init_check(future=180)
        self.assertNoReport(self.check, self.source)
