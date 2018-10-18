from functools import partial
import os
import tempfile

from pkgcore.ebuild import repository
from pkgcore.test.misc import FakePkg, FakeRepo
from snakeoil import fileutils
from snakeoil.currying import post_curry
from snakeoil.osutils import pjoin
from snakeoil.test.mixins import TempDirMixin

from pkgcheck import metadata_checks, addons
from pkgcheck.test import misc


class TestDescriptionReport(misc.ReportTestCase):

    check_kls = metadata_checks.DescriptionReport

    def mk_pkg(self, desc=""):
        return misc.FakePkg("dev-util/diffball-0.7.1", data={"DESCRIPTION": desc})

    def test_it(self):
        check = metadata_checks.DescriptionReport(None, None)

        self.assertNoReport(check, self.mk_pkg("a perfectly written package description"))

        assert isinstance(
            self.assertReport(check, self.mk_pkg("based on eclass")),
            metadata_checks.BadDescription)
        assert isinstance(
            self.assertReport(check, self.mk_pkg("diffball")),
            metadata_checks.BadDescription)
        assert isinstance(
            self.assertReport(check, self.mk_pkg("dev-util/diffball")),
            metadata_checks.BadDescription)
        assert isinstance(
            self.assertReport(check, self.mk_pkg("foon")),
            metadata_checks.BadDescription)

        # length-based checks
        assert isinstance(
            self.assertReport(check, self.mk_pkg()),
            metadata_checks.BadDescription)
        assert isinstance(
            self.assertReport(check, self.mk_pkg("s"*151)),
            metadata_checks.BadDescription)
        self.assertNoReport(check, self.mk_pkg("s"*150))
        assert isinstance(
            self.assertReport(check, self.mk_pkg("s"*9)),
            metadata_checks.BadDescription)
        self.assertNoReport(check, self.mk_pkg("s"*10))


class iuse_options(TempDirMixin):

    def get_options(self, **kwds):
        repo_base = tempfile.mkdtemp(dir=self.dir)
        base = pjoin(repo_base, 'profiles')
        os.mkdir(base)
        fileutils.write_file(
            pjoin(base, "arch.list"), 'w',
            "\n".join(kwds.pop("arches", ("x86", "ppc", "amd64", "amd64-fbsd"))))

        fileutils.write_file(
            pjoin(base, "use.desc"), "w",
            "\n".join(f"{x} - {x}" for x in kwds.pop("use_desc", ("foo", "bar"))))

        fileutils.write_file(pjoin(base, 'repo_name'), 'w', 'monkeys')
        os.mkdir(pjoin(repo_base, 'metadata'))
        fileutils.write_file(
            pjoin(repo_base, 'metadata', 'layout.conf'), 'w', "masters = ")
        kwds['target_repo'] = repository._UnconfiguredTree(repo_base)
        kwds['verbose'] = kwds.get('verbose', None)
        return misc.Options(**kwds)


class TestKeywordsReport(iuse_options, misc.ReportTestCase):

    check_kls = metadata_checks.KeywordsReport

    def setUp(self):
        super().setUp()
        options = self.get_options()
        profiles = [misc.FakeProfile()]
        iuse_handler = addons.UseAddon(options, profiles, silence_warnings=True)
        self.check = metadata_checks.KeywordsReport(options, iuse_handler)

    def mk_pkg(self, keywords=""):
        return misc.FakePkg("dev-util/diffball-0.7.1", data={"KEYWORDS": keywords})

    def test_stupid_keywords(self):
        assert isinstance(
            self.assertReport(self.check, self.mk_pkg("-*")),
            metadata_checks.StupidKeywords)
        self.assertNoReport(
            self.check, self.mk_pkg("-* ~x86"),
            metadata_checks.StupidKeywords)
        self.assertNoReport(
            self.check, self.mk_pkg("ppc"),
            metadata_checks.StupidKeywords)

    def test_invalid_keywords(self):
        assert isinstance(
            self.assertReport(self.check, self.mk_pkg("foo")),
            metadata_checks.InvalidKeywords)
        self.assertNoReport(
            self.check, self.mk_pkg("-* * ~* -amd64 ppc ~x86"),
            metadata_checks.InvalidKeywords)

    def test_unsorted_keywords(self):
        assert isinstance(
            self.assertReport(self.check, self.mk_pkg("~amd64 -*")),
            metadata_checks.UnsortedKeywords)
        self.assertNoReport(
            self.check, self.mk_pkg("-* ~amd64"),
            metadata_checks.UnsortedKeywords)
        assert isinstance(
            self.assertReport(self.check, self.mk_pkg("~amd64 ~amd64-fbsd ppc ~x86")),
            metadata_checks.UnsortedKeywords)
        self.assertNoReport(
            self.check, self.mk_pkg("~amd64 ppc ~x86 ~amd64-fbsd"),
            metadata_checks.UnsortedKeywords)


class TestIUSEMetadataReport(iuse_options, misc.ReportTestCase):

    check_kls = metadata_checks.IUSEMetadataReport

    def mk_pkg(self, iuse=""):
        return misc.FakePkg("dev-util/diffball-0.7.1", data={"IUSE": iuse})

    def test_it(self):
        # verify behaviour when use.* data isn't available
        options = self.get_options()
        profiles = [misc.FakeProfile()]
        check = metadata_checks.IUSEMetadataReport(
            options, addons.UseAddon(options, profiles))
        check.start()
        self.assertNoReport(check, self.mk_pkg("foo bar"))
        r = self.assertReport(check, self.mk_pkg("foo dar"))
        assert r.attr == "iuse"
        # arch flags must _not_ be in IUSE
        self.assertReport(check, self.mk_pkg("x86"))


class TestRequiredUSEMetadataReport(iuse_options, misc.ReportTestCase):

    check_kls = metadata_checks.RequiredUSEMetadataReport

    def setUp(self):
        super().setUp()
        options = self.get_options(verbose=1)
        profiles = {'x86': [misc.FakeProfile(name='default/linux/x86')]}
        self.check = metadata_checks.RequiredUSEMetadataReport(
            options, addons.UseAddon(options, profiles['x86']), profiles)
        self.check.start()

    def mk_pkg(self, eapi="4", iuse="", required_use="", keywords="x86"):
        return FakePkg(
            "dev-util/diffball-0.7.1",
            eapi=eapi,
            iuse=iuse.split(),
            data={"REQUIRED_USE": required_use, "KEYWORDS": keywords})

    def test_required_use(self):
        # bad syntax
        r = self.assertReport(self.check, self.mk_pkg(iuse="foo bar", required_use="| ( foo bar )"))
        assert isinstance(r, metadata_checks.MetadataError)

        # useless constructs
        r = self.assertReport(self.check, self.mk_pkg(iuse="foo bar", required_use="foo? ( )"))
        assert isinstance(r, metadata_checks.MetadataError)
        r = self.assertReport(self.check, self.mk_pkg(iuse="foo bar", required_use="|| ( )"))
        assert isinstance(r, metadata_checks.MetadataError)

        # only supported in >= EAPI 5
        self.assertReport(self.check, self.mk_pkg(iuse="foo bar", required_use="?? ( foo bar )"))
        self.assertNoReport(self.check, self.mk_pkg(eapi="5", iuse="foo bar", required_use="?? ( foo bar )"))

    def test_required_use_unstated_iuse(self):
        r = self.assertReport(self.check, self.mk_pkg(required_use="foo? ( blah )"))
        assert isinstance(r, addons.UnstatedIUSE)
        assert r.flags == ("blah", "foo")
        r = self.assertReport(self.check, self.mk_pkg(iuse="foo bar", required_use="foo? ( blah )"))
        assert isinstance(r, addons.UnstatedIUSE)
        assert r.flags == ("blah",)

    def test_required_use_defaults(self):
        # simple, valid IUSE/REQUIRED_USE usage
        self.assertNoReport(self.check, self.mk_pkg(iuse="foo bar"))
        self.assertNoReport(self.check, self.mk_pkg(iuse="+foo", required_use="foo"))
        self.assertNoReport(self.check, self.mk_pkg(iuse="foo bar", required_use="foo? ( bar )"))

        # unsatisfied REQUIRED_USE
        r = self.assertReport(self.check, self.mk_pkg(iuse="foo bar", required_use="bar"))
        assert isinstance(r, metadata_checks.RequiredUseDefaults)
        assert r.keyword == 'x86'
        assert r.profile == 'default/linux/x86'
        assert r.use == ()
        assert str(r.required_use) == 'bar'

        # at-most-one-of
        self.assertNoReport(self.check, self.mk_pkg(eapi="5", iuse="foo bar", required_use="?? ( foo bar )"))
        self.assertNoReport(self.check, self.mk_pkg(eapi="5", iuse="+foo bar", required_use="?? ( foo bar )"))
        self.assertNoReport(self.check, self.mk_pkg(eapi="5", iuse="foo +bar", required_use="?? ( foo bar )"))
        r = self.assertReport(self.check, self.mk_pkg(eapi="5", iuse="+foo +bar", required_use="?? ( foo bar )"))
        assert isinstance(r, metadata_checks.RequiredUseDefaults)
        assert r.use == ('bar', 'foo')
        assert str(r.required_use) == 'at-most-one-of ( foo bar )'

        # exactly-one-of
        self.assertNoReport(self.check, self.mk_pkg(iuse="+foo bar", required_use="^^ ( foo bar )"))
        self.assertNoReport(self.check, self.mk_pkg(iuse="foo +bar", required_use="^^ ( foo bar )"))
        self.assertReport(self.check, self.mk_pkg(iuse="foo bar", required_use="^^ ( foo bar )"))
        r = self.assertReport(self.check, self.mk_pkg(iuse="+foo +bar", required_use="^^ ( foo bar )"))
        assert isinstance(r, metadata_checks.RequiredUseDefaults)
        assert r.use == ('bar', 'foo')
        assert str(r.required_use) == 'exactly-one-of ( foo bar )'

        # all-of
        self.assertNoReport(self.check, self.mk_pkg(iuse="foo bar baz", required_use="foo? ( bar baz )"))
        self.assertNoReport(self.check, self.mk_pkg(iuse="+foo +bar +baz", required_use="foo? ( bar baz )"))
        self.assertReports(self.check, self.mk_pkg(iuse="+foo bar baz", required_use="foo? ( bar baz )"))
        self.assertReport(self.check, self.mk_pkg(iuse="+foo +bar baz", required_use="foo? ( bar baz )"))
        r = self.assertReport(self.check, self.mk_pkg(iuse="+foo bar +baz", required_use="foo? ( bar baz )"))
        assert isinstance(r, metadata_checks.RequiredUseDefaults)
        assert r.use == ('baz', 'foo')
        # TODO: fix this output to show both required USE flags
        assert str(r.required_use) == 'bar'

        # any-of
        self.assertNoReport(self.check, self.mk_pkg(iuse="foo bar baz", required_use="foo? ( || ( bar baz ) )"))
        self.assertNoReport(self.check, self.mk_pkg(iuse="+foo +bar baz", required_use="foo? ( || ( bar baz ) )"))
        self.assertNoReport(self.check, self.mk_pkg(iuse="+foo bar +baz", required_use="foo? ( || ( bar baz ) )"))
        self.assertNoReport(self.check, self.mk_pkg(iuse="+foo +bar +baz", required_use="foo? ( || ( bar baz ) )"))
        r = self.assertReport(self.check, self.mk_pkg(iuse="+foo bar baz", required_use="foo? ( || ( bar baz ) )"))
        assert isinstance(r, metadata_checks.RequiredUseDefaults)
        assert r.use == ('foo',)
        assert str(r.required_use) == '( bar || baz )'


def use_based():
    # hidden to keep the test runner from finding it.
    class use_based(iuse_options):

        def test_required_addons(self):
            assert addons.UseAddon in self.check_kls.required_addons

        def mk_check(self, **kwargs):
            options = self.get_options(**kwargs)
            profiles = [misc.FakeProfile(iuse_effective=["x86"])]
            iuse_handler = addons.UseAddon(options, profiles, silence_warnings=True)
            check = self.check_kls(options, iuse_handler)
            check.start()
            return check

    return use_based


class TestRestrictsReport(use_based(), misc.ReportTestCase):

    check_kls = metadata_checks.RestrictsReport

    def mk_pkg(self, restrict=''):
        return misc.FakePkg(
            'dev-util/diffball-2.7.1', data={'RESTRICT': restrict})

    def test_it(self):
        check = self.mk_check()
        self.assertNoReport(check, self.mk_pkg('primaryuri userpriv'))
        self.assertNoReport(check, self.mk_pkg('primaryuri x86? ( userpriv )'))
        self.assertReport(check, self.mk_pkg('pkgcore'))
        self.assertReport(check, self.mk_pkg('x86? ( pkgcore )'))


class TestLicenseMetadataReport(use_based(), misc.ReportTestCase):

    check_kls = metadata_checks.LicenseMetadataReport

    def mk_check(self, licenses=(), **kwargs):
        self.repo = FakeRepo(repo_id='test', licenses=licenses)
        options = self.get_options(**kwargs)
        profiles = [misc.FakeProfile()]
        iuse_handler = addons.UseAddon(options, profiles, silence_warnings=True)
        check = self.check_kls(options, iuse_handler, {})
        check.start()
        return check

    def mk_pkg(self, license='', iuse=''):
        return FakePkg(
            'dev-util/diffball-2.7.1',
            data={'LICENSE': license, 'IUSE': iuse},
            repo=self.repo)

    def test_malformed(self):
        r = self.assertReport(self.mk_check(), self.mk_pkg("|| ("))
        assert isinstance(r, metadata_checks.MetadataError)
        assert r.attr == 'license'

    def test_it(self):
        # should puke a metadata error for empty license
        chk = self.mk_check()
        assert isinstance(
            self.assertReport(chk, self.mk_pkg()),
            metadata_checks.MetadataError)
        r = self.assertReport(chk, self.mk_pkg("foo"))
        assert isinstance(r, metadata_checks.MissingLicense)
        assert r.licenses == ('foo',)

        chk = self.mk_check(['foo', 'foo2'])
        self.assertNoReport(chk, self.mk_pkg('foo'))
        self.assertNoReport(chk, self.mk_pkg('foo', 'foo2'))


class TestDependencyReport(use_based(), misc.ReportTestCase):

    check_kls = metadata_checks.DependencyReport

    attr_map = dict(
        (x, x.rstrip("s").upper())
        for x in ("depends", "rdepends"))
    attr_map['post_rdepends'] = 'PDEPEND'

    def mk_pkg(self, attr, data='', eapi='0', iuse=''):
        return misc.FakePkg(
            'dev-util/diffball-2.7.1',
            data={'EAPI': eapi, 'IUSE': iuse, self.attr_map[attr]: data})

    def generic_check(self, attr):
        # should puke a metadata error for empty license
        chk = self.mk_check()
        mk_pkg = partial(self.mk_pkg, attr)
        self.assertNoReport(chk, mk_pkg())
        self.assertNoReport(chk, mk_pkg("|| ( dev-util/foo ) dev-foo/bugger "))
        r = self.assertReport(self.mk_check(), mk_pkg("|| ("))
        assert isinstance(r, metadata_checks.MetadataError)
        assert r.attr == attr
        if 'depend' not in attr:
            return
        self.assertNoReport(chk, mk_pkg("!dev-util/blah"))
        r = self.assertReport(self.mk_check(), mk_pkg("!dev-util/diffball"))
        assert isinstance(r, metadata_checks.MetadataError)
        assert "blocks itself" in r.msg

        # check for := in || () blocks
        r = self.assertReport(
            self.mk_check(),
            mk_pkg(eapi='5', data="|| ( dev-libs/foo:= dev-libs/bar:= )"))
        assert isinstance(r, metadata_checks.MetadataError)
        assert "= slot operator used inside || block" in r.msg
        assert "[dev-libs/bar, dev-libs/foo]" in r.msg

        # check for := in blockers
        r = self.assertReport(
            self.mk_check(),
            mk_pkg(eapi='5', data="!dev-libs/foo:="))
        assert isinstance(r, metadata_checks.MetadataError)
        assert "= slot operator used in blocker" in r.msg
        assert "[dev-libs/foo]" in r.msg

        # check for missing revisions
        r = self.assertReport(
            self.mk_check(),
            mk_pkg(eapi='6', data="=dev-libs/foo-1"))
        assert isinstance(r, metadata_checks.MissingRevision)

    for x in attr_map:
        locals()[f"test_{x}"] = post_curry(generic_check, x)
    del x


class TestSrcUriReport(use_based(), misc.ReportTestCase):

    check_kls = metadata_checks.SrcUriReport

    def mk_pkg(self, src_uri='', default_chksums={"size": 100},
               iuse='', disable_chksums=False):
        class fake_repo:
            def __init__(self, default_chksums):
                if disable_chksums:
                    self.chksums = {}
                else:
                    self.chksums = {}.fromkeys(
                        set(os.path.basename(x) for x in src_uri.split()),
                        default_chksums)

            def _get_digests(self, pkg, allow_missing=False):
                return False, self.chksums

        class fake_parent:
            _parent_repo = fake_repo(default_chksums)

        return misc.FakePkg(
            'dev-util/diffball-2.7.1',
            data={'SRC_URI': src_uri, 'IUSE': iuse},
            parent=fake_parent())

    def test_malformed(self):
        r = self.assertReport(
            self.mk_check(), self.mk_pkg("foon", disable_chksums=True))
        assert isinstance(r, metadata_checks.MetadataError)
        assert r.attr == 'fetchables'

    def test_bad_filename(self):
        chk = self.mk_check()
        assert isinstance(
            self.assertReport(chk, self.mk_pkg("https://foon.com/2.7.1.tar.gz")),
            metadata_checks.BadFilename)
        assert isinstance(
            self.assertReport(chk, self.mk_pkg("https://foon.com/v2.7.1.zip")),
            metadata_checks.BadFilename)
        assert isinstance(
            self.assertReport(chk, self.mk_pkg("https://foon.com/cb230f01fb288a0b9f0fc437545b97d06c846bd3.tar.gz")),
            metadata_checks.BadFilename)

    def test_it(self):
        chk = self.mk_check()
        # ensure it pukes about RESTRICT!=fetch, and no uri

        r = self.assertReport(chk, self.mk_pkg("foon"))
        assert isinstance(r, metadata_checks.MissingUri)
        assert r.filename == 'foon'

        # verify valid protos.
        assert self.check_kls.valid_protos, "valid_protos needs to have at least one protocol"

        for x in self.check_kls.valid_protos:
            self.assertNoReport(
                chk, self.mk_pkg(f"{x}://dar.com/foon"),
                msg=f"testing valid proto {x}")

        # grab a proto, and mangle it.
        bad_proto = list(self.check_kls.valid_protos)[0]
        while bad_proto in self.check_kls.valid_protos:
            bad_proto += "s"

        r = self.assertReport(chk, self.mk_pkg(f"{bad_proto}://foon.com/foon"))
        assert isinstance(r, metadata_checks.BadProto)

        assert r.filename == 'foon'
        assert list(r.bad_uri) == [f'{bad_proto}://foon.com/foon']

        # check collapsing.

        r = self.assertReport(
                chk,
                self.mk_pkg(f"{bad_proto}://foon.com/foon {bad_proto}://dar.com/foon"))
        assert isinstance(r, metadata_checks.BadProto)

        assert r.filename == 'foon'
        assert list(r.bad_uri) == sorted(f'{bad_proto}://{x}/foon' for x in ('foon.com', 'dar.com'))
