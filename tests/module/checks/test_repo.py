import os

from pkgcore.ebuild import atom
from pkgcore.test.misc import FakeRepo
from snakeoil.osutils import pjoin

from pkgcheck.checks import repo

from .. import misc


class TestRepoDirCheck(misc.Tmpdir, misc.ReportTestCase):

    check_kls = repo.RepoDirCheck

    def mk_check(self):
        self.repo = FakeRepo(repo_id='repo', location=self.dir)
        options = misc.Options(target_repo=self.repo)
        return repo.RepoDirCheck(options)

    def mk_pkg(self, cpvstr):
        pkg = atom.atom(cpvstr)
        filesdir = pjoin(self.repo.location, pkg.category, pkg.package, 'files')
        os.makedirs(filesdir)
        return filesdir

    def test_empty_repo(self):
        self.assertNoReport(self.mk_check(), [])

    def test_ignored_root_dirs(self):
        check = self.mk_check()
        bin_path = pjoin(self.repo.location, '.git', 'foo')
        os.makedirs(os.path.dirname(bin_path))
        with open(bin_path, 'wb') as f:
            f.write(b'\xd3\xad\xbe\xef')
        self.assertNoReport(check, [])

    def test_root_dir_binary(self):
        check = self.mk_check()
        bin_path = pjoin(self.repo.location, 'foo')
        os.makedirs(os.path.dirname(bin_path), exist_ok=True)
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

    def test_non_utf8_encodings(self):
        check = self.mk_check()
        filesdir = self.mk_pkg('dev-util/foo')
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
            with open(pjoin(filesdir, 'foo'), 'wb') as f:
                f.write(text.encode(encoding=encoding))
            self.assertNoReport(check, [])
