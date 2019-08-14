from functools import partial
from itertools import combinations
import os
import tempfile
import textwrap

from pkgcore.ebuild import eapi, repository
from pkgcore.test.misc import FakePkg, FakeRepo
from snakeoil import fileutils
from snakeoil.currying import post_curry
from snakeoil.osutils import pjoin
from snakeoil.test.mixins import TempDirMixin

from pkgcheck import addons
from pkgcheck.checks import metadata

from .. import misc


class TestDescriptionReport(misc.ReportTestCase):

    check_kls = metadata.DescriptionCheck

    def mk_pkg(self, desc=""):
        return misc.FakePkg("dev-util/diffball-0.7.1", data={"DESCRIPTION": desc})

    def test_it(self):
        check = metadata.DescriptionCheck(None, None)

        self.assertNoReport(check, self.mk_pkg("a perfectly written package description"))

        assert isinstance(
            self.assertReport(check, self.mk_pkg("based on eclass")),
            metadata.BadDescription)
        assert isinstance(
            self.assertReport(check, self.mk_pkg("diffball")),
            metadata.BadDescription)
        assert isinstance(
            self.assertReport(check, self.mk_pkg("dev-util/diffball")),
            metadata.BadDescription)
        assert isinstance(
            self.assertReport(check, self.mk_pkg("foon")),
            metadata.BadDescription)

        # length-based checks
        assert isinstance(
            self.assertReport(check, self.mk_pkg()),
            metadata.BadDescription)
        assert isinstance(
            self.assertReport(check, self.mk_pkg("s"*151)),
            metadata.BadDescription)
        self.assertNoReport(check, self.mk_pkg("s"*150))
        assert isinstance(
            self.assertReport(check, self.mk_pkg("s"*9)),
            metadata.BadDescription)
        self.assertNoReport(check, self.mk_pkg("s"*10))


class TestHomepageCheck(misc.ReportTestCase):

    check_kls = metadata.HomepageCheck
    check = metadata.HomepageCheck(None, None)

    def mk_pkg(self, homepage=""):
        return misc.FakePkg("dev-util/diffball-0.7.1", data={"HOMEPAGE": homepage})

    def test_regular(self):
        self.assertNoReport(self.check, self.mk_pkg("https://foobar.com"))

    def test_multiple(self):
        pkg = self.mk_pkg("https://foobar.com http://foob.org")
        assert len(pkg.homepage) == 2
        self.assertNoReport(self.check, pkg)

    def test_unset(self):
        r = self.assertReport(self.check, self.mk_pkg())
        isinstance(r, metadata.BadHomepage)
        assert 'empty/unset' in str(r)

    def test_no_protocol(self):
        r = self.assertReport(self.check, self.mk_pkg('foobar.com'))
        isinstance(r, metadata.BadHomepage)
        assert 'lacks protocol' in str(r)

    def test_unsupported_protocol(self):
        r = self.assertReport(self.check, self.mk_pkg('htp://foobar.com'))
        isinstance(r, metadata.BadHomepage)
        assert "uses unsupported protocol 'htp'" in str(r)

    def test_missing_categories(self):
        for category in self.check_kls.missing_categories:
            pkg = misc.FakePkg(f"{category}/foo-1", data={"HOMEPAGE": "http://foo.com"})
            r = self.assertReport(self.check, pkg)
            isinstance(r, metadata.BadHomepage)
            assert f"'{category}' packages shouldn't define HOMEPAGE" in str(r)


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

        fileutils.write_file(pjoin(base, 'repo_name'), 'w', kwds.pop('repo_name', 'monkeys'))
        os.mkdir(pjoin(repo_base, 'metadata'))
        with open(pjoin(repo_base, 'metadata', 'layout.conf'), 'w') as f:
            f.write(textwrap.dedent("""\
                masters =
                properties-allowed = interactive live
                restrict-allowed = binchecks bindist fetch installsources mirror preserve-libs primaryuri splitdebug strip test userpriv
            """))
        kwds['target_repo'] = repository.UnconfiguredTree(repo_base)
        kwds.setdefault('verbosity', 0)
        kwds.setdefault('git_disable', True)
        return misc.Options(**kwds)


class TestKeywordsCheck(iuse_options, misc.ReportTestCase):

    check_kls = metadata.KeywordsCheck

    def setUp(self):
        super().setUp()
        options = self.get_options()
        profiles = [misc.FakeProfile()]
        iuse_handler = addons.UseAddon(options, profiles, silence_warnings=True)
        self.check = metadata.KeywordsCheck(options, iuse_handler)

    def mk_pkg(self, keywords=""):
        return misc.FakePkg("dev-util/diffball-0.7.1", data={"KEYWORDS": keywords})

    def test_no_keywords(self):
        self.assertNoReport(self.check, self.mk_pkg())

    def test_stupid_keywords(self):
        # regular keywords
        self.assertNoReport(self.check, self.mk_pkg("ppc"))
        # masked all except a single arch
        self.assertNoReport(self.check, self.mk_pkg("-* ~x86"))
        # all keywords masked
        r = self.assertReport(self.check, self.mk_pkg("-*"))
        assert isinstance(r, metadata.StupidKeywords)
        assert 'keywords contain -*' in str(r)

    def test_invalid_keywords(self):
        # regular keywords
        self.assertNoReport(self.check, self.mk_pkg("-* -amd64 ppc ~x86"))
        self.assertNoReport(self.check, self.mk_pkg("* -amd64 ppc ~x86"))
        self.assertNoReport(self.check, self.mk_pkg("~* -amd64 ppc ~x86"))

        # unknown keyword
        r = self.assertReport(self.check, self.mk_pkg("foo"))
        assert isinstance(r, metadata.InvalidKeywords)
        assert r.keywords == ('foo',)
        assert "invalid KEYWORDS: 'foo'" == str(r)

        # check that * and ~* are flagged in gentoo repo
        options = self.get_options(repo_name='gentoo')
        profiles = [misc.FakeProfile()]
        iuse_handler = addons.UseAddon(options, profiles, silence_warnings=True)
        check = metadata.KeywordsCheck(options, iuse_handler)
        r = self.assertReport(check, self.mk_pkg("*"))
        assert isinstance(r, metadata.InvalidKeywords)
        assert r.keywords == ('*',)
        assert "invalid KEYWORDS: '*'" == str(r)
        r = self.assertReport(check, self.mk_pkg("~*"))
        assert isinstance(r, metadata.InvalidKeywords)
        assert r.keywords == ('~*',)
        assert "invalid KEYWORDS: '~*'" == str(r)

    def test_overlapping_keywords(self):
        # regular keywords
        self.assertNoReport(self.check, self.mk_pkg("~* ~amd64"))

        # overlapping stable and unstable keywords
        r = self.assertReport(self.check, self.mk_pkg("amd64 ~amd64"))
        assert isinstance(r, metadata.OverlappingKeywords)
        assert r.keywords == (('amd64', '~amd64'),)
        assert "overlapping KEYWORDS: ('amd64', '~amd64')" == str(r)

        # multiple overlapping sets
        r = self.assertReport(self.check, self.mk_pkg("amd64 ~amd64 ~x86 x86"))
        assert isinstance(r, metadata.OverlappingKeywords)
        assert r.keywords == (('amd64', '~amd64'), ('x86', '~x86'))

    def test_duplicate_keywords(self):
        # regular keywords
        self.assertNoReport(self.check, self.mk_pkg("~* ~amd64"))

        # single duplicate
        r = self.assertReport(self.check, self.mk_pkg("amd64 amd64"))
        assert isinstance(r, metadata.DuplicateKeywords)
        assert r.keywords == ('amd64',)
        assert 'duplicate KEYWORDS: amd64' == str(r)

        # multiple duplicates
        r = self.assertReport(self.check, self.mk_pkg("-* -* amd64 amd64 ~x86 ~x86"))
        assert isinstance(r, metadata.DuplicateKeywords)
        assert r.keywords == ('-*', 'amd64', '~x86')

    def test_unsorted_keywords(self):
        # regular keywords
        self.assertNoReport(self.check, self.mk_pkg('-* ~amd64'))

        # prefix keywords come after regular keywords
        self.assertNoReport(self.check, self.mk_pkg('~amd64 ppc ~x86 ~amd64-fbsd'))

        # masks should come before regular keywords
        r = self.assertReport(self.check, self.mk_pkg('~amd64 -*'))
        assert isinstance(r, metadata.UnsortedKeywords)
        assert r.keywords == ('~amd64', '-*')
        assert r.sorted_keywords == ('-*', '~amd64')
        assert 'unsorted KEYWORDS: ~amd64, -*' == str(r)
        # verbose output
        r._verbosity = 1
        assert '\n\tunsorted: ~amd64, -*\n\tsorted: -*, ~amd64' == str(r)

        # keywords should be sorted alphabetically by arch
        r = self.assertReport(self.check, self.mk_pkg('ppc ~amd64'))
        assert isinstance(r, metadata.UnsortedKeywords)
        assert r.keywords == ('ppc', '~amd64')
        assert r.sorted_keywords == ('~amd64', 'ppc')
        assert 'unsorted KEYWORDS: ppc, ~amd64' == str(r)
        # verbose output
        r._verbosity = 1
        assert '\n\tunsorted: ppc, ~amd64\n\tsorted: ~amd64, ppc' == str(r)

        # prefix keywords should come after regular keywords
        r = self.assertReport(self.check, self.mk_pkg('~amd64 ~amd64-fbsd ppc ~x86'))
        assert isinstance(r, metadata.UnsortedKeywords)
        assert r.keywords == ('~amd64', '~amd64-fbsd', 'ppc', '~x86')
        assert r.sorted_keywords == ('~amd64', 'ppc', '~x86', '~amd64-fbsd')


class TestIUSEMetadataReport(iuse_options, misc.ReportTestCase):

    check_kls = metadata.IUSEMetadataCheck

    def mk_pkg(self, iuse=""):
        return misc.FakePkg("dev-util/diffball-0.7.1", data={"IUSE": iuse})

    def test_it(self):
        # verify behaviour when use.* data isn't available
        options = self.get_options()
        profiles = [misc.FakeProfile()]
        check = metadata.IUSEMetadataCheck(
            options, addons.UseAddon(options, profiles))
        self.assertNoReport(check, self.mk_pkg("foo bar"))
        r = self.assertReport(check, self.mk_pkg("foo dar"))
        assert r.attr == "iuse"
        # arch flags must _not_ be in IUSE
        self.assertReport(check, self.mk_pkg("x86"))


class TestRequiredUSEMetadataReport(iuse_options, misc.ReportTestCase):

    check_kls = metadata.RequiredUSEMetadataCheck

    def setUp(self):
        super().setUp()
        self.check = self.mk_check()

    def mk_check(self, masks=(), verbosity=1, profiles=None):
        if profiles is None:
            profiles = {'x86': [misc.FakeProfile(name='default/linux/x86', masks=masks)]}
        options = self.get_options(verbosity=verbosity)
        check = self.check_kls(options, addons.UseAddon(options, profiles['x86']), profiles)
        return check

    def mk_pkg(self, cpvstr="dev-util/diffball-0.7.1", eapi="4", iuse="",
               required_use="", keywords="~amd64 x86"):
        return FakePkg(
            cpvstr,
            eapi=eapi,
            iuse=iuse.split(),
            data={"REQUIRED_USE": required_use, "KEYWORDS": keywords})

    def test_unsupported_eapis(self):
        for eapi_str, eapi_obj in eapi.EAPI.known_eapis.items():
            if not eapi_obj.options.has_required_use:
                pkg = self.mk_pkg(eapi=eapi_str, required_use="foo? ( blah )")
                self.assertNoReport(self.check, pkg)

    def test_multireport_verbosity(self):
        profiles = {
            'x86': [
                misc.FakeProfile(name='default/linux/x86', masks=()),
                misc.FakeProfile(name='default/linux/x86/foo', masks=())]
        }
        # non-verbose mode should only one failure per node
        check = self.mk_check(verbosity=0, profiles=profiles)
        r = self.assertReport(check, self.mk_pkg(iuse="+foo bar", required_use="bar"))
        assert "profile: 'default/linux/x86' (2 total) failed REQUIRED_USE: bar" == str(r)
        # while verbose mode should report both
        check = self.mk_check(verbosity=1, profiles=profiles)
        r = self.assertReports(check, self.mk_pkg(iuse="+foo bar", required_use="bar"))
        assert "keyword: x86, profile: 'default/linux/x86', default USE: [foo] " in str(r[0])
        assert "keyword: x86, profile: 'default/linux/x86/foo', default USE: [foo]" in str(r[1])

    def test_required_use(self):
        # bad syntax
        r = self.assertReport(self.check, self.mk_pkg(iuse="foo bar", required_use="| ( foo bar )"))
        assert isinstance(r, metadata.MetadataError)

        # useless constructs
        r = self.assertReport(self.check, self.mk_pkg(iuse="foo bar", required_use="foo? ( )"))
        assert isinstance(r, metadata.MetadataError)
        r = self.assertReport(self.check, self.mk_pkg(iuse="foo bar", required_use="|| ( )"))
        assert isinstance(r, metadata.MetadataError)

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

        # pkgs masked by the related profile aren't checked
        self.assertNoReport(
            self.mk_check(masks=('>=dev-util/diffball-8.0',)),
            self.mk_pkg(cpvstr="dev-util/diffball-8.0", iuse="foo bar", required_use="bar"))

        # unsatisfied REQUIRED_USE
        r = self.assertReport(self.check, self.mk_pkg(iuse="foo bar", required_use="bar"))
        assert isinstance(r, metadata.RequiredUseDefaults)
        assert r.keyword == 'x86'
        assert r.profile == 'default/linux/x86'
        assert r.use == ()
        assert str(r.required_use) == 'bar'

        # at-most-one-of
        self.assertNoReport(self.check, self.mk_pkg(eapi="5", iuse="foo bar", required_use="?? ( foo bar )"))
        self.assertNoReport(self.check, self.mk_pkg(eapi="5", iuse="+foo bar", required_use="?? ( foo bar )"))
        self.assertNoReport(self.check, self.mk_pkg(eapi="5", iuse="foo +bar", required_use="?? ( foo bar )"))
        r = self.assertReport(self.check, self.mk_pkg(eapi="5", iuse="+foo +bar", required_use="?? ( foo bar )"))
        assert isinstance(r, metadata.RequiredUseDefaults)
        assert r.use == ('bar', 'foo')
        assert str(r.required_use) == 'at-most-one-of ( foo bar )'

        # exactly-one-of
        self.assertNoReport(self.check, self.mk_pkg(iuse="+foo bar", required_use="^^ ( foo bar )"))
        self.assertNoReport(self.check, self.mk_pkg(iuse="foo +bar", required_use="^^ ( foo bar )"))
        self.assertReport(self.check, self.mk_pkg(iuse="foo bar", required_use="^^ ( foo bar )"))
        r = self.assertReport(self.check, self.mk_pkg(iuse="+foo +bar", required_use="^^ ( foo bar )"))
        assert isinstance(r, metadata.RequiredUseDefaults)
        assert r.use == ('bar', 'foo')
        assert str(r.required_use) == 'exactly-one-of ( foo bar )'

        # all-of
        self.assertNoReport(self.check, self.mk_pkg(iuse="foo bar baz", required_use="foo? ( bar baz )"))
        self.assertNoReport(self.check, self.mk_pkg(iuse="+foo +bar +baz", required_use="foo? ( bar baz )"))
        self.assertReports(self.check, self.mk_pkg(iuse="+foo bar baz", required_use="foo? ( bar baz )"))
        self.assertReport(self.check, self.mk_pkg(iuse="+foo +bar baz", required_use="foo? ( bar baz )"))
        r = self.assertReport(self.check, self.mk_pkg(iuse="+foo bar +baz", required_use="foo? ( bar baz )"))
        assert isinstance(r, metadata.RequiredUseDefaults)
        assert r.use == ('baz', 'foo')
        # TODO: fix this output to show both required USE flags
        assert str(r.required_use) == 'bar'

        # any-of
        self.assertNoReport(self.check, self.mk_pkg(iuse="foo bar baz", required_use="foo? ( || ( bar baz ) )"))
        self.assertNoReport(self.check, self.mk_pkg(iuse="+foo +bar baz", required_use="foo? ( || ( bar baz ) )"))
        self.assertNoReport(self.check, self.mk_pkg(iuse="+foo bar +baz", required_use="foo? ( || ( bar baz ) )"))
        self.assertNoReport(self.check, self.mk_pkg(iuse="+foo +bar +baz", required_use="foo? ( || ( bar baz ) )"))
        r = self.assertReport(self.check, self.mk_pkg(iuse="+foo bar baz", required_use="foo? ( || ( bar baz ) )"))
        assert isinstance(r, metadata.RequiredUseDefaults)
        assert r.use == ('foo',)
        assert str(r.required_use) == '( bar || baz )'


def use_based():
    # hidden to keep the test runner from finding it.
    class use_based(iuse_options):

        def test_required_addons(self):
            assert addons.UseAddon in self.check_kls.required_addons

        def mk_check(self, *args, **kwargs):
            options = self.get_options(**kwargs)
            profiles = [misc.FakeProfile(iuse_effective=["x86"])]
            iuse_handler = addons.UseAddon(options, profiles, silence_warnings=True)
            check = self.check_kls(options, iuse_handler, *args)
            return check

    return use_based


class TestRestrictsReport(use_based(), misc.ReportTestCase):

    check_kls = metadata.RestrictsCheck

    def mk_pkg(self, restrict=''):
        return misc.FakePkg(
            'dev-util/diffball-2.7.1', data={'RESTRICT': restrict})

    def test_it(self):
        check = self.mk_check()
        self.assertNoReport(check, self.mk_pkg('primaryuri userpriv'))
        self.assertNoReport(check, self.mk_pkg('primaryuri x86? ( userpriv )'))
        self.assertReport(check, self.mk_pkg('pkgcore'))
        self.assertReport(check, self.mk_pkg('x86? ( pkgcore )'))


class TestConditionalTestRestrictCheck(misc.ReportTestCase):

    check_kls = metadata.ConditionalTestRestrictCheck

    def mk_pkg(self, iuse='', restrict=''):
        return misc.FakePkg(
            'dev-util/diffball-2.7.1', data={'IUSE': iuse, 'RESTRICT': restrict})

    def test_it(self):
        check = self.check_kls(None)
        self.assertNoReport(check, self.mk_pkg())
        self.assertNoReport(check, self.mk_pkg(
            iuse='test', restrict='!test? ( test )'))
        # unconditional restriction is fine too
        self.assertNoReport(check, self.mk_pkg(iuse='test', restrict='test'))
        self.assertNoReport(check, self.mk_pkg(restrict='test'))
        # more RESTRICTs
        self.assertNoReport(check, self.mk_pkg(iuse='foo test',
            restrict='foo? ( strip ) !test? ( test ) bindist'))

        # missing entirely
        self.assertReport(check, self.mk_pkg(iuse='test'))
        # 'test' present in other condition
        self.assertReport(check, self.mk_pkg(
            iuse='foo test', restrict='!foo? ( test )'))
        # correct restriction inside another condition
        self.assertReport(check, self.mk_pkg(
            iuse='foo test', restrict='!foo? ( !test? ( test ) )'))
        # USE condition gotten the other way around
        self.assertReport(check, self.mk_pkg(
            iuse='test', restrict='test? ( test )'))


class TestLicenseMetadataCheck(use_based(), misc.ReportTestCase):

    check_kls = metadata.LicenseMetadataCheck

    def mk_check(self, licenses=(), **kwargs):
        self.repo = FakeRepo(repo_id='test', licenses=licenses)
        options = self.get_options(**kwargs)
        profiles = [misc.FakeProfile()]
        iuse_handler = addons.UseAddon(options, profiles, silence_warnings=True)
        check = self.check_kls(options, iuse_handler, {})
        return check

    def mk_pkg(self, license='', iuse=''):
        return FakePkg(
            'dev-util/diffball-2.7.1',
            data={'LICENSE': license, 'IUSE': iuse},
            repo=self.repo)

    def test_malformed(self):
        r = self.assertReport(self.mk_check(), self.mk_pkg("|| ("))
        assert isinstance(r, metadata.MetadataError)
        assert r.attr == 'license'

    def test_empty(self):
        r = self.assertReport(self.mk_check(), self.mk_pkg())
        assert isinstance(r, metadata.MetadataError)

    def test_single_missing(self):
        r = self.assertReport(self.mk_check(), self.mk_pkg("foo"))
        assert isinstance(r, metadata.MissingLicense)
        assert r.licenses == ('foo',)
        assert 'no matching license: [ foo ]' == str(r)

    def test_multiple_existing(self):
        chk = self.mk_check(['foo', 'foo2'])
        self.assertNoReport(chk, self.mk_pkg('foo'))
        self.assertNoReport(chk, self.mk_pkg('foo', 'foo2'))

    def test_multiple_missing(self):
        chk = self.mk_check(['foo', 'foo2'])
        r = self.assertReport(chk, self.mk_pkg('|| ( foo foo3 foo4 )'))
        assert isinstance(r, metadata.MissingLicense)
        assert r.licenses == ('foo3', 'foo4')
        assert 'no matching licenses: [ foo3, foo4 ]' == str(r)

    def test_unlicensed_categories(self):
        check = self.mk_check(['foo'])
        for category in self.check_kls.unlicensed_categories:
            for license in ('foo', ''):
                pkg = FakePkg(
                    f'{category}/diffball-2.7.1',
                    data={'LICENSE': license},
                    repo=self.repo)
                if license:
                    r = self.assertReport(check, pkg)
                    assert isinstance(r, metadata.UnnecessaryLicense)
                    assert f"{category!r} packages shouldn't define LICENSE" in str(r)
                else:
                    self.assertNoReport(check, pkg)


class TestMissingSlotDepCheck(use_based(), misc.ReportTestCase):

    check_kls = metadata.MissingSlotDepCheck

    def mk_check(self, pkgs=None, **kwargs):
        if pkgs is None:
            pkgs = (
                FakePkg('dev-libs/foo-0', slot='0'),
                FakePkg('dev-libs/foo-1', slot='1'),
                FakePkg('dev-libs/bar-2', slot='2'),
            )
        self.repo = FakeRepo(pkgs=pkgs, repo_id='test')
        options = self.get_options(**kwargs)
        profiles = [misc.FakeProfile()]
        iuse_handler = addons.UseAddon(options, profiles, silence_warnings=True)
        check = self.check_kls(options, iuse_handler)
        return check

    def mk_pkg(self, eapi='5', rdepend='', depend=''):
        return FakePkg(
            'dev-util/diffball-2.7.1', eapi=eapi,
            data={'RDEPEND': rdepend, 'DEPEND': depend},
            repo=self.repo)

    def test_unsupported_eapis(self):
        # EAPIs lacking slot operator deps shouldn't trigger reports
        for eapi_str, eapi_obj in eapi.EAPI.known_eapis.items():
            if not eapi_obj.options.sub_slotting:
                self.assertNoReport(
                    self.mk_check(), self.mk_pkg(
                        eapi=eapi_str, rdepend='dev-lbs/foo', depend='dev-libs/foo'))

    def test_supported_eapis(self):
        for eapi_str, eapi_obj in eapi.EAPI.known_eapis.items():
            if eapi_obj.options.sub_slotting:
                r = self.assertReport(
                    self.mk_check(), self.mk_pkg(
                        eapi=eapi_str, rdepend='dev-libs/foo', depend='dev-libs/foo'))
                assert isinstance(r, metadata.MissingSlotDep)
                assert "'dev-libs/foo' matches more than one slot: [ 0, 1 ]" == str(r)

    def test_no_deps(self):
        self.assertNoReport(self.mk_check(), self.mk_pkg())

    def test_single_slot_dep(self):
        self.assertNoReport(
            self.mk_check(), self.mk_pkg(rdepend='dev-libs/bar', depend='dev-libs/bar'))


class TestDependencyCheck(use_based(), misc.ReportTestCase):

    check_kls = metadata.DependencyCheck

    attr_map = dict(
        (x, x.upper())
        for x in ("depend", "rdepend", "pdepend", "bdepend"))

    def mk_pkg(self, attr, data='', eapi='0', iuse=''):
        if attr == 'bdepend':
            eapi = '7'
        return misc.FakePkg(
            'dev-util/diffball-2.7.1',
            data={'EAPI': eapi, 'IUSE': iuse, self.attr_map[attr]: data})

    def mk_check(self, pkgs=None, **kwargs):
        if pkgs is None:
            pkgs = (
                FakePkg('dev-libs/foo-0', slot='0', iuse=('bar',)),
                FakePkg('dev-libs/foo-1', slot='1', iuse=('bar', 'baz')),
                FakePkg('dev-libs/bar-2', slot='2'),
            )
        kwargs['search_repo'] = FakeRepo(pkgs=pkgs, repo_id='test')
        options = self.get_options(**kwargs)
        git_addon = addons.GitAddon(options)
        return super().mk_check(git_addon, **kwargs)

    def generic_check(self, attr):
        # should puke a metadata error for empty license
        chk = self.mk_check()
        mk_pkg = partial(self.mk_pkg, attr)
        self.assertNoReport(chk, mk_pkg())
        self.assertNoReport(chk, mk_pkg("|| ( dev-util/foo ) dev-foo/bugger "))
        r = self.assertReport(chk, mk_pkg("|| ("))
        assert isinstance(r, metadata.MetadataError)
        assert r.attr == attr
        if 'depend' not in attr:
            return
        self.assertNoReport(chk, mk_pkg("!dev-util/blah"))
        r = self.assertReport(chk, mk_pkg("!dev-util/diffball"))
        assert isinstance(r, metadata.MetadataError)
        assert "blocks itself" in r.msg

        # check for := in || () blocks
        r = self.assertReport(
            chk,
            mk_pkg(eapi='5', data="|| ( dev-libs/foo:= dev-libs/bar:= )"))
        assert isinstance(r, metadata.MetadataError)
        assert "= slot operator used inside || block" in r.msg
        assert "[dev-libs/bar, dev-libs/foo]" in r.msg

        # check for := in blockers
        r = self.assertReport(
            chk,
            mk_pkg(eapi='5', data="!dev-libs/foo:="))
        assert isinstance(r, metadata.MetadataError)
        assert "= slot operator used in blocker" in r.msg
        assert "[dev-libs/foo]" in r.msg

        # check for missing package revisions
        self.assertNoReport(chk, mk_pkg("=dev-libs/foo-1-r0"))
        r = self.assertReport(
            chk,
            mk_pkg(eapi='6', data="=dev-libs/foo-1"))
        assert isinstance(r, metadata.MissingPackageRevision)
        assert f'{attr.upper()}="=dev-libs/foo-1"' in str(r)

        # MissingUseDepDefault checks

        # USE flag exists on all matching pkgs
        self.assertNoReport(chk, mk_pkg(eapi='4', data='dev-libs/foo[bar?]'))

        # USE flag doesn't exist but has proper default
        self.assertNoReport(chk, mk_pkg(eapi='4', data='dev-libs/bar[foo(-)?]'))
        self.assertNoReport(chk, mk_pkg(eapi='4', data='dev-libs/bar[foo(+)=]'))
        self.assertNoReport(chk, mk_pkg(eapi='4', data='dev-libs/bar[!foo(-)?]'))
        self.assertNoReport(chk, mk_pkg(eapi='4', data='!dev-libs/bar[!foo(+)?]'))

        # matching pkg doesn't have any USE flags
        r = self.assertReport(chk, mk_pkg(eapi='4', data='dev-libs/bar[foo?]'))
        assert isinstance(r, metadata.MissingUseDepDefault)
        assert r.atom == 'dev-libs/bar[foo?]'
        assert r.pkg_deps == ('=dev-libs/bar-2',)
        assert r.flag == 'foo'
        assert "USE flag 'foo' missing" in str(r)

        # blocker triggers result as well
        r = self.assertReport(chk, mk_pkg(eapi='4', data='!dev-libs/bar[foo?]'))
        assert isinstance(r, metadata.MissingUseDepDefault)
        assert r.atom == '!dev-libs/bar[foo?]'
        assert r.pkg_deps == ('=dev-libs/bar-2',)
        assert r.flag == 'foo'
        assert "USE flag 'foo' missing" in str(r)

        # USE flag missing on one of multiple matches
        r = self.assertReport(chk, mk_pkg(eapi='4', data='dev-libs/foo[baz?]'))
        assert isinstance(r, metadata.MissingUseDepDefault)
        assert r.atom == 'dev-libs/foo[baz?]'
        assert r.pkg_deps == ('=dev-libs/foo-0',)
        assert r.flag == 'baz'
        assert "USE flag 'baz' missing" in str(r)

        # USE flag missing on all matches
        r = self.assertReport(chk, mk_pkg(eapi='4', data='dev-libs/foo[blah?]'))
        assert isinstance(r, metadata.MissingUseDepDefault)
        assert r.atom == 'dev-libs/foo[blah?]'
        assert r.pkg_deps == ('=dev-libs/foo-0', '=dev-libs/foo-1')
        assert r.flag == 'blah'
        assert "USE flag 'blah' missing" in str(r)

    for x in attr_map:
        locals()[f"test_{x}"] = post_curry(generic_check, x)
    del x


class TestSrcUriReport(use_based(), misc.ReportTestCase):

    check_kls = metadata.SrcUriCheck

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
        assert isinstance(r, metadata.MetadataError)
        assert r.attr == 'fetchables'

    def test_bad_filename(self):
        chk = self.mk_check()
        assert isinstance(
            self.assertReport(chk, self.mk_pkg("https://foon.com/2.7.1.tar.gz")),
            metadata.BadFilename)
        assert isinstance(
            self.assertReport(chk, self.mk_pkg("https://foon.com/v2.7.1.zip")),
            metadata.BadFilename)
        assert isinstance(
            self.assertReport(chk, self.mk_pkg("https://foon.com/cb230f01fb288a0b9f0fc437545b97d06c846bd3.tar.gz")),
            metadata.BadFilename)

    def test_it(self):
        chk = self.mk_check()
        # ensure it pukes about RESTRICT!=fetch, and no uri

        r = self.assertReport(chk, self.mk_pkg("foon"))
        assert isinstance(r, metadata.MissingUri)
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
        assert isinstance(r, metadata.BadProto)

        assert r.filename == 'foon'
        assert list(r.bad_uri) == [f'{bad_proto}://foon.com/foon']

        # check collapsing.

        r = self.assertReport(
                chk,
                self.mk_pkg(f"{bad_proto}://foon.com/foon {bad_proto}://dar.com/foon"))
        assert isinstance(r, metadata.BadProto)

        assert r.filename == 'foon'
        assert list(r.bad_uri) == sorted(f'{bad_proto}://{x}/foon' for x in ('foon.com', 'dar.com'))

    def test_tarball_available_github(self):
        chk = self.mk_check()
        uri = "https://github.com/foo/bar/archive/v1.2.3.zip"
        r = self.assertReport(chk, self.mk_pkg(uri))
        assert isinstance(r, metadata.TarballAvailable)
        assert r.uris == (uri,)

    def test_tarball_available_gitlab(self):
        chk = self.mk_check()
        uri = "https://gitlab.com/foo/bar/-/archive/v1.2.3/bar-v1.2.3.zip"
        r = self.assertReport(chk, self.mk_pkg(uri))
        assert isinstance(r, metadata.TarballAvailable)
        assert r.uris == (uri,)


class TestMissingUnpackerDepCheck(use_based(), misc.ReportTestCase):

    check_kls = metadata.MissingUnpackerDepCheck

    def mk_pkg(self, exts, eapi='7', **data):
        if isinstance(exts, str):
            exts = [exts]

        class fake_repo:
            def _get_digests(self, pkg, allow_missing=False):
                chksums = {f'diffball-2.7.1{ext}': {'size': 100} for ext in exts}
                return False, chksums

        data['SRC_URI'] = ' '.join(
            f'https://foo.com/diffball-2.7.1{ext}' for ext in exts)
        return FakePkg(
            'dev-util/diffball-2.7.1', data=data, eapi=eapi, repo=fake_repo())

    def test_with_system_dep(self):
        self.assertNoReport(self.mk_check(), self.mk_pkg('.tar.gz'))

    def test_keyword_output(self):
        # unpacker deps go in BDEPEND in EAPI >= 7
        r = self.assertReport(self.mk_check(), self.mk_pkg('.jar', eapi='7'))
        assert 'missing BDEPEND="app-arch/unzip"' in str(r)
        # and in DEPEND for EAPI < 7
        r = self.assertReport(self.mk_check(), self.mk_pkg('.jar', eapi='6'))
        assert 'missing DEPEND="app-arch/unzip"' in str(r)

    def test_without_dep(self):
        for ext, unpackers in self.check_kls.non_system_unpackers.items():
            pkg = self.mk_pkg(ext)
            r = self.assertReport(self.mk_check(), pkg)
            assert isinstance(r, metadata.MissingUnpackerDep)
            assert r.filenames == (f'diffball-2.7.1{ext}',)
            assert r.unpackers == tuple(
                sorted(map(str, self.check_kls.non_system_unpackers[ext])))

    def test_with_dep(self):
        for ext, unpackers in self.check_kls.non_system_unpackers.items():
            for dep_type in ('DEPEND', 'BDEPEND'):
                for unpacker in unpackers:
                    kwargs = {dep_type: unpacker.cpvstr}
                    pkg = self.mk_pkg(ext, **kwargs)
                    self.assertNoReport(self.mk_check(), pkg)

    def test_rar_with_or_dep(self):
        self.assertNoReport(
            self.mk_check(),
            self.mk_pkg('.rar', DEPEND='|| ( app-arch/rar app-arch/unrar )'))

    def test_without_multiple_unpackers(self):
        for combination in combinations(self.check_kls.non_system_unpackers.items(), 2):
            exts = list(x[0] for x in combination)
            unpackers = list(x[1] for x in combination)
            pkg = self.mk_pkg(exts)
            reports = self.assertReports(self.mk_check(), pkg)
            if len(reports) == 1:
                # some combinations are for extensions that share the same
                # unpacker so they will be combined in one report
                assert len(set(unpackers)) == 1
                r = reports[0]
                assert isinstance(r, metadata.MissingUnpackerDep)
                assert r.filenames == tuple(sorted(f'diffball-2.7.1{ext}' for ext in exts))
                assert r.unpackers == tuple(sorted(map(str, unpackers[0])))
            else:
                assert len(reports) == 2
                for i, r in enumerate(reports):
                    assert isinstance(r, metadata.MissingUnpackerDep)
                    assert r.filenames == (f'diffball-2.7.1{exts[i]}',)
                    assert r.unpackers == tuple(sorted(map(str, unpackers[i])))

    def test_with_multiple_unpackers_one_missing(self):
        r = self.assertReport(
            self.mk_check(),
            self.mk_pkg(['.zip', '.7z'], DEPEND='app-arch/unzip'))
        assert isinstance(r, metadata.MissingUnpackerDep)
        assert r.filenames == (f'diffball-2.7.1.7z',)
        assert r.unpackers == ('app-arch/p7zip',)
