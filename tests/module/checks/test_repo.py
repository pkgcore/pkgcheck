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
        # english -- (other languages courtesy of google translate mangling)
        with open(pjoin(filesdir, 'foo'), 'wb') as f:
            f.write(b"example text that shouldn't trigger")
        self.assertNoReport(check, [])
        # arabic
        with open(pjoin(filesdir, 'foo'), 'wb') as f:
            f.write('نص المثال الذي لا ينبغي أن يؤدي'.encode(encoding='cp1256'))
        self.assertNoReport(check, [])
        # russian
        with open(pjoin(filesdir, 'foo'), 'wb') as f:
            f.write('пример текста, который не должен срабатывать'.encode(encoding='koi8_r'))
        self.assertNoReport(check, [])
        # hindi
        with open(pjoin(filesdir, 'foo'), 'wb') as f:
            f.write('उदाहरण पाठ जो ट्रिगर नहीं होना चाहिए'.encode(encoding='utf-16'))
        self.assertNoReport(check, [])
        # urdu
        with open(pjoin(filesdir, 'foo'), 'wb') as f:
            f.write('مثال کے متن جو ٹرگر نہ ہوں۔'.encode(encoding='utf-16'))
        self.assertNoReport(check, [])
        # burmese
        with open(pjoin(filesdir, 'foo'), 'wb') as f:
            f.write('ဖြစ်ပေါ်မပေးသင့်ကြောင်းဥပမာစာသား'.encode(encoding='utf-32'))
        self.assertNoReport(check, [])
        # nepali
        with open(pjoin(filesdir, 'foo'), 'wb') as f:
            f.write('उदाहरण पाठ जुन ट्रिगर हुँदैन'.encode(encoding='utf-32'))
        self.assertNoReport(check, [])
        # japanese
        with open(pjoin(filesdir, 'foo'), 'wb') as f:
            f.write('トリガーするべきではないテキストの例'.encode(encoding='shift_jis'))
        self.assertNoReport(check, [])
        # korean
        with open(pjoin(filesdir, 'foo'), 'wb') as f:
            f.write('트리거해서는 안되는 예제 텍스트'.encode(encoding='cp949'))
        self.assertNoReport(check, [])
        # simplified chinese
        with open(pjoin(filesdir, 'foo'), 'wb') as f:
            f.write('不应触发的示例文本'.encode(encoding='gb2312'))
        self.assertNoReport(check, [])
        # traditional chinese
        with open(pjoin(filesdir, 'foo'), 'wb') as f:
            f.write('不應觸發的示例文本'.encode(encoding='gb18030'))
        self.assertNoReport(check, [])
