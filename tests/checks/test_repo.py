import os
from unittest import mock

from pkgcheck import addons
from pkgcheck.checks import repo
from pkgcore.ebuild import atom
from pkgcore.test.misc import FakeRepo
from snakeoil.cli import arghparse
from snakeoil.fileutils import touch
from snakeoil.osutils import ensure_dirs, pjoin

from .. import misc


class TestRepoDirCheck(misc.Tmpdir, misc.ReportTestCase):

    check_kls = repo.RepoDirCheck

    def mk_check(self):
        self.repo = FakeRepo(repo_id='repo', location=self.dir)
        options = arghparse.Namespace(
            target_repo=self.repo, cache={'git': False}, gentoo_repo=True)
        git_addon = addons.git.GitAddon(options)
        return repo.RepoDirCheck(options, git_addon=git_addon)

    def mk_pkg(self, cpvstr):
        pkg = atom.atom(cpvstr)
        filesdir = pjoin(self.repo.location, pkg.category, pkg.package, 'files')
        os.makedirs(filesdir, exist_ok=True)
        return filesdir

    def test_empty_repo(self):
        self.assertNoReport(self.mk_check(), [])

    def test_empty_file(self):
        check = self.mk_check()
        bin_path = pjoin(self.repo.location, 'foo')
        touch(bin_path)
        self.assertNoReport(check, [])

    def test_regular_file(self):
        check = self.mk_check()
        with open(pjoin(self.repo.location, 'foo'), 'w') as f:
            f.write('bar')
        self.assertNoReport(check, [])

    def test_unreadable_file(self):
        check = self.mk_check()
        with open(pjoin(self.repo.location, 'foo'), 'w') as f:
            f.write('bar')
        with mock.patch('pkgcheck.open') as mocked_open:
            mocked_open.side_effect = IOError('fake exception')
            self.assertNoReport(check, [])

    def test_ignored_root_dirs(self):
        for d in self.check_kls.ignored_root_dirs:
            check = self.mk_check()
            bin_path = pjoin(self.repo.location, d, 'foo')
            os.makedirs(os.path.dirname(bin_path))
            with open(bin_path, 'wb') as f:
                f.write(b'\xd3\xad\xbe\xef')
            self.assertNoReport(check, [])

    def test_null_bytes(self):
        check = self.mk_check()
        with open(pjoin(self.repo.location, 'foo'), 'wb') as f:
            f.write(b'foo\x00\xffbar')
        r = self.assertReport(check, [])
        assert isinstance(r, repo.BinaryFile)
        assert r.path == 'foo'
        assert "'foo'" in str(r)

    def test_root_dir_binary(self):
        check = self.mk_check()
        bin_path = pjoin(self.repo.location, 'foo')
        with open(bin_path, 'wb') as f:
            f.write(b'\xd3\xad\xbe\xef')
        r = self.assertReport(check, [])
        assert isinstance(r, repo.BinaryFile)
        assert r.path == 'foo'
        assert "'foo'" in str(r)

    def test_ebuild_filesdir_binary(self):
        check = self.mk_check()
        filesdir = self.mk_pkg('dev-util/foo')
        with open(pjoin(filesdir, 'foo'), 'wb') as f:
            f.write(b'\xd3\xad\xbe\xef')
        r = self.assertReport(check, [])
        assert isinstance(r, repo.BinaryFile)
        assert r.path == 'dev-util/foo/files/foo'
        assert "'dev-util/foo/files/foo'" in str(r)

    def test_gitignore(self):
        # distfiles located in deprecated in-tree location are reported by default
        check = self.mk_check()
        distfiles = pjoin(self.repo.location, 'distfiles')
        os.mkdir(distfiles)
        with open(pjoin(distfiles, 'foo-0.tar.gz'), 'wb') as f:
            f.write(b'\xd3\xad\xbe\xef')
        r = self.assertReport(check, [])
        assert isinstance(r, repo.BinaryFile)
        assert "distfiles/foo-0.tar.gz" in str(r)

        # but results are suppressed if a matching git ignore entry exists
        for ignore_file in ('.gitignore', '.git/info/exclude'):
            path = pjoin(self.repo.location, ignore_file)
            ensure_dirs(os.path.dirname(path))
            with open(path, 'w') as f:
                f.write('/distfiles/')
            self.assertNoReport(self.mk_check(), [])
            os.unlink(path)

    def test_non_utf8_encodings(self):
        # non-english languages courtesy of google translate mangling
        langs = (
            ("example text that shouldn't trigger", 'ascii'),
            ('نص المثال الذي لا ينبغي أن يؤدي', 'cp1256'), # arabic
            ('пример текста, который не должен срабатывать', 'koi8_r'), # russian
            ('उदाहरण पाठ जो ट्रिगर नहीं होना चाहिए', 'utf-16'), # hindi
            ('مثال کے متن جو ٹرگر نہ ہوں۔', 'utf-16'), # urdu
            ('ဖြစ်ပေါ်မပေးသင့်ကြောင်းဥပမာစာသား', 'utf-32'), # burmese
            ('उदाहरण पाठ जुन ट्रिगर हुँदैन', 'utf-32'), # nepali
            ('トリガーするべきではないテキストの例', 'shift_jis'), # japanese
            ('트리거해서는 안되는 예제 텍스트', 'cp949'), # korean
            ('不应触发的示例文本', 'gb2312'), # simplified chinese
            ('不應觸發的示例文本', 'gb18030'), # traditional chinese
        )
        for text, encoding in langs:
            check = self.mk_check()
            with open(pjoin(self.repo.location, 'foo'), 'wb') as f:
                data = text.encode(encoding)
                f.write(data)
            self.assertNoReport(check, [])
