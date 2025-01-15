import os
import tempfile
import textwrap
from datetime import datetime, timedelta
from functools import partial
from itertools import combinations
from operator import attrgetter

import pytest
from pkgcheck import addons
from pkgcheck.checks import metadata
from pkgcore.ebuild import eapi, repo_objs, repository
from pkgcore.ebuild.cpv import VersionedCPV as CPV
from pkgcore.test.misc import FakePkg, FakeRepo
from snakeoil.cli import arghparse
from snakeoil.osutils import pjoin

from .. import misc


class TestDescriptionCheck(misc.ReportTestCase):
    check_kls = metadata.DescriptionCheck
    check = metadata.DescriptionCheck(None)

    def mk_pkg(self, desc=""):
        return misc.FakePkg("dev-util/diffball-0.7.1", data={"DESCRIPTION": desc})

    def test_good_desc(self):
        self.assertNoReport(self.check, self.mk_pkg("a perfectly written package description"))

    def test_bad_descs(self):
        for desc in ("based on eclass", "diffball", "dev-util/diffball", "foon"):
            r = self.assertReport(self.check, self.mk_pkg(desc))
            assert isinstance(r, metadata.BadDescription)

    def test_desc_length(self):
        r = self.assertReport(self.check, self.mk_pkg())
        assert isinstance(r, metadata.BadDescription)
        assert "empty/unset" in str(r)

        self.assertNoReport(self.check, self.mk_pkg("s" * 80))
        r = self.assertReport(self.check, self.mk_pkg("s" * 81))
        assert isinstance(r, metadata.BadDescription)
        assert "over 80 chars in length" in str(r)

        self.assertNoReport(self.check, self.mk_pkg("s" * 10))
        r = self.assertReport(self.check, self.mk_pkg("s" * 9))
        assert isinstance(r, metadata.BadDescription)
        assert "under 10 chars in length" in str(r)


class TestHomepageCheck(misc.ReportTestCase):
    check_kls = metadata.HomepageCheck
    check = metadata.HomepageCheck(None)

    def mk_pkg(self, homepage="", cpvstr="dev-util/diffball-0.7.1"):
        return misc.FakePkg(cpvstr, data={"HOMEPAGE": homepage})

    def test_regular(self):
        self.assertNoReport(self.check, self.mk_pkg("https://foobar.com"))

    def test_multiple(self):
        pkg = self.mk_pkg("https://foobar.com http://foob.org")
        assert len(pkg.homepage) == 2
        self.assertNoReport(self.check, pkg)

    def test_unset(self):
        r = self.assertReport(self.check, self.mk_pkg())
        isinstance(r, metadata.BadHomepage)
        assert "empty/unset" in str(r)

        # categories of pkgs allowed to skip HOMEPAGE
        for cat in self.check_kls.missing_categories:
            self.assertNoReport(self.check, self.mk_pkg(cpvstr=f"{cat}/foo-0"))

    def test_no_protocol(self):
        r = self.assertReport(self.check, self.mk_pkg("foobar.com"))
        isinstance(r, metadata.BadHomepage)
        assert "lacks protocol" in str(r)

    def test_unsupported_protocol(self):
        r = self.assertReport(self.check, self.mk_pkg("htp://foobar.com"))
        isinstance(r, metadata.BadHomepage)
        assert "uses unsupported protocol 'htp'" in str(r)

    def test_unspecific_site(self):
        for suffix in ("", "/"):
            for site in ("https://www.gentoo.org", "https://gentoo.org"):
                r = self.assertReport(self.check, self.mk_pkg(f"{site}{suffix}"))
                isinstance(r, metadata.BadHomepage)
                assert "unspecific HOMEPAGE" in str(r)

    def test_missing_categories(self):
        for category in self.check_kls.missing_categories:
            pkg = misc.FakePkg(f"{category}/foo-1", data={"HOMEPAGE": "http://foo.com"})
            r = self.assertReport(self.check, pkg)
            isinstance(r, metadata.BadHomepage)
            assert f"HOMEPAGE should be undefined for '{category}' packages" in str(r)


class IUSE_Options(misc.Tmpdir):
    def get_options(self, properties=(), restrict=(), **kwargs):
        repo_base = tempfile.mkdtemp(dir=self.dir)
        base = pjoin(repo_base, "profiles")
        os.mkdir(base)
        with open(pjoin(base, "arch.list"), "w") as file:
            file.write("\n".join(kwargs.pop("arches", ("x86", "ppc", "amd64", "amd64-fbsd"))))
        with open(pjoin(base, "use.desc"), "w") as file:
            file.write("\n".join(f"{x} - {x}" for x in kwargs.pop("use_desc", ("foo", "bar"))))
        with open(pjoin(base, "repo_name"), "w") as file:
            file.write(kwargs.pop("repo_name", "monkeys"))
        os.mkdir(pjoin(repo_base, "metadata"))
        with open(pjoin(repo_base, "metadata", "layout.conf"), "w") as f:
            f.write(
                textwrap.dedent(
                    f"""\
                        masters =
                        properties-allowed = {' '.join(properties)}
                        restrict-allowed = {' '.join(restrict)}
                    """
                )
            )
        kwargs["target_repo"] = repository.UnconfiguredTree(repo_base)
        kwargs.setdefault("verbosity", 0)
        kwargs.setdefault("cache", {"git": False})
        return arghparse.Namespace(**kwargs)


class TestKeywordsCheck(IUSE_Options, misc.ReportTestCase):
    check_kls = metadata.KeywordsCheck

    @pytest.fixture
    def check(self):
        pkgs = (
            FakePkg("dev-libs/foo-0", keywords=("amd64", "~x86")),
            FakePkg("dev-libs/foo-1", keywords=("-*", "ppc")),
            FakePkg("dev-libs/bar-2", keywords=()),
        )
        search_repo = FakeRepo(pkgs=pkgs)
        options = self.get_options(search_repo=search_repo, gentoo_repo=False)

        kwargs = {
            "use_addon": addons.UseAddon(options),
            "keywords_addon": addons.KeywordsAddon(options),
        }
        return metadata.KeywordsCheck(options, **kwargs)

    def mk_pkg(self, keywords="", cpv="dev-util/diffball-0.7.1", rdepend=""):
        return misc.FakePkg(cpv, data={"KEYWORDS": keywords, "RDEPEND": rdepend})

    def test_no_keywords(self, check):
        self.assertNoReport(check, self.mk_pkg())

    def test_bad_keywords(self, check):
        # regular keywords
        self.assertNoReport(check, self.mk_pkg("ppc"))
        # masked all except a single arch
        self.assertNoReport(check, self.mk_pkg("-* ~x86"))
        # all keywords masked
        r = self.assertReport(check, self.mk_pkg("-*"))
        assert isinstance(r, metadata.BadKeywords)
        assert 'KEYWORDS="-*"' in str(r)

    def test_invalid_keywords(self, check):
        # regular keywords
        self.assertNoReport(check, self.mk_pkg("-* -amd64 ppc ~x86"))
        self.assertNoReport(check, self.mk_pkg("* -amd64 ppc ~x86"))
        self.assertNoReport(check, self.mk_pkg("~* -amd64 ppc ~x86"))

        # unknown keyword
        r = self.assertReport(check, self.mk_pkg("foo"))
        assert isinstance(r, metadata.UnknownKeywords)
        assert r.keywords == ("foo",)
        assert "unknown KEYWORDS: 'foo'" in str(r)

        # check that * and ~* are flagged in gentoo repo
        options = self.get_options(repo_name="gentoo", gentoo_repo=True)
        kwargs = {
            "use_addon": addons.UseAddon(options),
            "keywords_addon": addons.KeywordsAddon(options),
        }
        check = metadata.KeywordsCheck(options, **kwargs)
        r = self.assertReport(check, self.mk_pkg("*"))
        assert isinstance(r, metadata.UnknownKeywords)
        assert r.keywords == ("*",)
        assert "unknown KEYWORDS: '*'" in str(r)
        r = self.assertReport(check, self.mk_pkg("~*"))
        assert isinstance(r, metadata.UnknownKeywords)
        assert r.keywords == ("~*",)
        assert "unknown KEYWORDS: '~*'" in str(r)

    def test_overlapping_keywords(self, check):
        # regular keywords
        self.assertNoReport(check, self.mk_pkg("~* ~amd64"))

        # overlapping stable and unstable keywords
        r = self.assertReport(check, self.mk_pkg("amd64 ~amd64"))
        assert isinstance(r, metadata.OverlappingKeywords)
        assert r.keywords == "('amd64', '~amd64')"
        assert "overlapping KEYWORDS: ('amd64', '~amd64')" in str(r)

        # multiple overlapping sets
        r = self.assertReport(check, self.mk_pkg("amd64 ~amd64 ~x86 x86"))
        assert isinstance(r, metadata.OverlappingKeywords)
        assert r.keywords == "('amd64', '~amd64'), ('x86', '~x86')"

    def test_duplicate_keywords(self, check):
        # regular keywords
        self.assertNoReport(check, self.mk_pkg("~* ~amd64"))

        # single duplicate
        r = self.assertReport(check, self.mk_pkg("amd64 amd64"))
        assert isinstance(r, metadata.DuplicateKeywords)
        assert r.keywords == ("amd64",)
        assert "duplicate KEYWORDS: amd64" in str(r)

        # multiple duplicates
        r = self.assertReport(check, self.mk_pkg("-* -* amd64 amd64 ~x86 ~x86"))
        assert isinstance(r, metadata.DuplicateKeywords)
        assert r.keywords == ("-*", "amd64", "~x86")

    def test_unsorted_keywords(self, check):
        # regular keywords
        self.assertNoReport(check, self.mk_pkg("-* ~amd64"))

        # prefix keywords come after regular keywords
        self.assertNoReport(check, self.mk_pkg("~amd64 ppc ~x86 ~amd64-fbsd"))

        # non-verbose mode doesn't show sorted keywords
        r = self.assertReport(check, self.mk_pkg("~amd64 -*"))
        assert isinstance(r, metadata.UnsortedKeywords)
        assert r.keywords == ("~amd64", "-*")
        assert r.sorted_keywords == ()
        assert "unsorted KEYWORDS: ~amd64, -*" in str(r)

        # create a check instance with verbose mode enabled
        options = self.get_options(gentoo_repo=False, verbosity=1)
        kwargs = {
            "use_addon": addons.UseAddon(options),
            "keywords_addon": addons.KeywordsAddon(options),
        }
        check = metadata.KeywordsCheck(options, **kwargs)

        # masks should come before regular keywords
        r = self.assertReport(check, self.mk_pkg("~amd64 -*"))
        assert isinstance(r, metadata.UnsortedKeywords)
        assert r.keywords == ("~amd64", "-*")
        assert r.sorted_keywords == ("-*", "~amd64")
        assert "\n\tunsorted KEYWORDS: ~amd64, -*\n\tsorted KEYWORDS: -*, ~amd64" in str(r)

        # keywords should be sorted alphabetically by arch
        r = self.assertReport(check, self.mk_pkg("ppc ~amd64"))
        assert isinstance(r, metadata.UnsortedKeywords)
        assert r.keywords == ("ppc", "~amd64")
        assert r.sorted_keywords == ("~amd64", "ppc")
        assert "\n\tunsorted KEYWORDS: ppc, ~amd64\n\tsorted KEYWORDS: ~amd64, ppc" in str(r)

        # prefix keywords should come after regular keywords
        r = self.assertReport(check, self.mk_pkg("~amd64 ~amd64-fbsd ppc ~x86"))
        assert isinstance(r, metadata.UnsortedKeywords)
        assert r.keywords == ("~amd64", "~amd64-fbsd", "ppc", "~x86")
        assert r.sorted_keywords == ("~amd64", "ppc", "~x86", "~amd64-fbsd")

    def test_missing_virtual_keywords(self, check):
        # non-virtuals don't trigger
        pkg = self.mk_pkg(cpv="dev-util/foo-0", rdepend="=dev-libs/foo-0")
        self.assertNoReport(check, pkg)

        # matching pkg with no keywords
        pkg = self.mk_pkg(cpv="virtual/foo-0", rdepend="dev-libs/bar")
        self.assertNoReport(check, pkg)

        # single pkg match
        pkg = self.mk_pkg(cpv="virtual/foo-0", rdepend="=dev-libs/foo-0")
        r = self.assertReport(check, pkg)
        assert isinstance(r, metadata.VirtualKeywordsUpdate)
        assert r.keywords == ("amd64", "~x86")
        assert "KEYWORDS updates available: amd64, ~x86" in str(r)

        # multiple pkg match
        pkg = self.mk_pkg(cpv="virtual/foo-0", rdepend="dev-libs/foo")
        r = self.assertReport(check, pkg)
        assert isinstance(r, metadata.VirtualKeywordsUpdate)
        assert r.keywords == ("amd64", "ppc", "~x86")
        assert "KEYWORDS updates available: amd64, ppc, ~x86" in str(r)


class TestIuseCheck(IUSE_Options, misc.ReportTestCase):
    check_kls = metadata.IuseCheck

    @pytest.fixture
    def check(self):
        options = self.get_options()
        use_addon = addons.UseAddon(options)
        return self.check_kls(options, use_addon=use_addon)

    def mk_pkg(self, iuse=""):
        return misc.FakePkg("dev-util/diffball-0.7.1", data={"IUSE": iuse, "EAPI": "1"})

    def test_known_iuse(self, check):
        self.assertNoReport(check, self.mk_pkg("foo bar"))

    def test_unknown_iuse(self, check):
        r = self.assertReport(check, self.mk_pkg("foo dar"))
        assert isinstance(r, metadata.UnknownUseFlags)
        assert r.flags == ("dar",)
        assert "dar" in str(r)

    def test_arch_iuse(self, check):
        # arch flags must _not_ be in IUSE
        r = self.assertReport(check, self.mk_pkg("x86"))
        assert isinstance(r, metadata.UnknownUseFlags)
        assert r.flags == ("x86",)
        assert "x86" in str(r)

    def test_invalid_iuse(self, check):
        for flag in ("+", "-", "@", "_"):
            r = self.assertReport(check, self.mk_pkg(f"foo {flag}"))
            assert isinstance(r, metadata.InvalidUseFlags)
            assert r.flags == (flag,)
            assert flag in str(r)


class TestEapiCheck(misc.ReportTestCase, misc.Tmpdir):
    check_kls = metadata.EapiCheck

    def mk_check(self, deprecated=(), banned=()):
        # TODO: switch to using a repo fixture when available
        os.makedirs(pjoin(self.dir, "profiles"))
        os.makedirs(pjoin(self.dir, "metadata"))
        with open(pjoin(self.dir, "profiles", "repo_name"), "w") as f:
            f.write("fake\n")
        with open(pjoin(self.dir, "metadata", "layout.conf"), "w") as f:
            f.write("masters =\n")
            f.write(f"eapis-deprecated = {' '.join(deprecated)}\n")
            f.write(f"eapis-banned = {' '.join(banned)}\n")
        repo_config = repo_objs.RepoConfig(location=self.dir)
        self.repo = repository.UnconfiguredTree(repo_config.location, repo_config=repo_config)
        options = arghparse.Namespace(target_repo=self.repo, verbosity=False)
        return self.check_kls(options, eclass_addon=addons.eclass.EclassAddon(options))

    def mk_pkg(self, eapi):
        return misc.FakePkg("dev-util/diffball-2.7.1", data={"EAPI": eapi})

    def test_repo_with_no_settings(self):
        check = self.mk_check()
        for eapi_str in eapi.EAPI.known_eapis.keys():
            self.assertNoReport(check, self.mk_pkg(eapi=eapi_str))

    def test_latest_eapi(self):
        check = self.mk_check(
            deprecated=("0", "2", "4", "5"),
            banned=(
                "1",
                "3",
            ),
        )
        latest_eapi = list(eapi.EAPI.known_eapis)[-1]
        self.assertNoReport(check, self.mk_pkg(eapi=latest_eapi))

    def test_deprecated_eapi(self):
        deprecated = ("0", "2", "4", "5")
        banned = ("1", "3")
        check = self.mk_check(deprecated=deprecated, banned=banned)
        for eapi_str in deprecated:
            r = self.assertReport(check, self.mk_pkg(eapi=eapi_str))
            assert isinstance(r, metadata.DeprecatedEapi)
            assert r.eapi == eapi_str
            assert f"uses deprecated EAPI {eapi_str}" in str(r)

    def test_banned_eapi(self):
        deprecated = ("0", "2", "4", "5")
        banned = ("1", "3")
        check = self.mk_check(deprecated=deprecated, banned=banned)
        for eapi_str in banned:
            r = self.assertReport(check, self.mk_pkg(eapi=eapi_str))
            assert isinstance(r, metadata.BannedEapi)
            assert r.eapi == eapi_str
            assert f"uses banned EAPI {eapi_str}" in str(r)


class TestSourcingCheck(misc.ReportTestCase, misc.Tmpdir):
    check_kls = metadata.SourcingCheck
    _repo_id = 0

    def mk_check(self):
        # TODO: switch to using a repo fixture when available
        repo_dir = pjoin(self.dir, str(self._repo_id))
        self._repo_id += 1
        os.makedirs(pjoin(repo_dir, "profiles"))
        os.makedirs(pjoin(repo_dir, "metadata"))
        with open(pjoin(repo_dir, "profiles", "repo_name"), "w") as f:
            f.write("fake\n")
        with open(pjoin(repo_dir, "metadata", "layout.conf"), "w") as f:
            f.write("masters =\n")
        repo_config = repo_objs.RepoConfig(location=repo_dir)
        self.repo = repository.UnconfiguredTree(repo_config.location, repo_config=repo_config)
        options = arghparse.Namespace(target_repo=self.repo, verbosity=False)
        return self.check_kls(options)

    def mk_pkg(self, eapi):
        return misc.FakePkg("dev-util/diffball-2.7.1", data={"EAPI": eapi})

    def test_repo_with_no_settings(self):
        check = self.mk_check()
        for eapi_str in eapi.EAPI.known_eapis.keys():
            self.assertNoReport(check, self.mk_pkg(eapi=eapi_str))

    def test_unknown_eapis(self):
        for eapi in ("blah", "9999"):
            check = self.mk_check()
            pkg_path = pjoin(self.repo.location, "dev-util", "foo")
            os.makedirs(pkg_path)
            with open(pjoin(pkg_path, "foo-0.ebuild"), "w") as f:
                f.write(f"EAPI={eapi}\n")
            r = self.assertReport(check, self.repo)
            assert isinstance(r, metadata.InvalidEapi)
            assert f"EAPI '{eapi}' is not supported" in str(r)

    def test_invalid_eapis(self):
        for eapi in ("invalid!", "${EAPI}"):
            check = self.mk_check()
            pkg_path = pjoin(self.repo.location, "dev-util", "foo")
            os.makedirs(pkg_path)
            with open(pjoin(pkg_path, "foo-0.ebuild"), "w") as f:
                f.write(f"EAPI={eapi}\n")
            r = self.assertReport(check, self.repo)
            assert isinstance(r, metadata.InvalidEapi)
            assert f"invalid EAPI '{eapi}'" in str(r)

    def test_sourcing_error(self):
        check = self.mk_check()
        pkg_path = pjoin(self.repo.location, "dev-util", "foo")
        os.makedirs(pkg_path)
        with open(pjoin(pkg_path, "foo-0.ebuild"), "w") as f:
            f.write("foo\n")
        r = self.assertReport(check, self.repo)
        assert isinstance(r, metadata.SourcingError)

    def test_invalid_slots(self):
        for slot in ("?", "0/1"):
            check = self.mk_check()
            pkg_path = pjoin(self.repo.location, "dev-util", "foo")
            os.makedirs(pkg_path)
            with open(pjoin(pkg_path, "foo-0.ebuild"), "w") as f:
                f.write(f"""SLOT="{slot}"\n""")
            r = self.assertReport(check, self.repo)
            assert isinstance(r, metadata.InvalidSlot)
            assert f"invalid SLOT: '{slot}'" in str(r)


class TestRequiredUseCheck(IUSE_Options, misc.ReportTestCase):
    check_kls = metadata.RequiredUseCheck

    @pytest.fixture
    def check(self):
        return self.mk_check()

    def mk_check(self, masks=(), verbosity=1, profiles=None):
        if profiles is None:
            profiles = {"x86": [misc.FakeProfile(name="default/linux/x86", masks=masks)]}
        options = self.get_options(verbosity=verbosity)
        use_addon = addons.UseAddon(options)
        check = self.check_kls(options, use_addon=use_addon, profile_addon=profiles)
        return check

    def mk_pkg(
        self,
        cpvstr="dev-util/diffball-0.7.1",
        eapi="4",
        iuse="",
        required_use="",
        keywords="~amd64 x86",
    ):
        return FakePkg(
            cpvstr,
            eapi=eapi,
            iuse=iuse.split(),
            data={"REQUIRED_USE": required_use, "KEYWORDS": keywords},
        )

    def test_unsupported_eapis(self, check):
        for eapi_str, eapi_obj in eapi.EAPI.known_eapis.items():
            if not eapi_obj.options.has_required_use:
                pkg = self.mk_pkg(eapi=eapi_str, required_use="foo? ( blah )")
                self.assertNoReport(check, pkg)

    def test_multireport_verbosity(self):
        profiles = {
            "x86": [
                misc.FakeProfile(name="default/linux/x86", masks=()),
                misc.FakeProfile(name="default/linux/x86/foo", masks=()),
            ]
        }
        # non-verbose mode should only one failure per node
        check = self.mk_check(verbosity=0, profiles=profiles)
        r = self.assertReport(check, self.mk_pkg(iuse="+foo bar", required_use="bar"))
        assert "profile: 'default/linux/x86' (2 total) failed REQUIRED_USE: bar" in str(r)
        # while verbose mode should report both
        check = self.mk_check(verbosity=1, profiles=profiles)
        r = self.assertReports(check, self.mk_pkg(iuse="+foo bar", required_use="bar"))
        assert "keyword: x86, profile: 'default/linux/x86', default USE: [foo] " in str(r[0])
        assert "keyword: x86, profile: 'default/linux/x86/foo', default USE: [foo]" in str(r[1])

    def test_required_use(self, check):
        # bad syntax
        r = self.assertReport(check, self.mk_pkg(iuse="foo bar", required_use="| ( foo bar )"))
        assert isinstance(r, metadata.InvalidRequiredUse)

        # useless constructs
        r = self.assertReport(check, self.mk_pkg(iuse="foo bar", required_use="foo? ( )"))
        assert isinstance(r, metadata.InvalidRequiredUse)
        r = self.assertReport(check, self.mk_pkg(iuse="foo bar", required_use="|| ( )"))
        assert isinstance(r, metadata.InvalidRequiredUse)

        # only supported in >= EAPI 5
        self.assertReport(check, self.mk_pkg(iuse="foo bar", required_use="?? ( foo bar )"))
        self.assertNoReport(
            check, self.mk_pkg(eapi="5", iuse="foo bar", required_use="?? ( foo bar )")
        )

    def test_unstated_iuse(self, check):
        r = self.assertReport(check, self.mk_pkg(required_use="foo? ( blah )"))
        assert isinstance(r, addons.UnstatedIuse)
        assert r.flags == ("blah", "foo")
        r = self.assertReport(check, self.mk_pkg(iuse="foo bar", required_use="foo? ( blah )"))
        assert isinstance(r, addons.UnstatedIuse)
        assert r.flags == ("blah",)

    def test_required_use_defaults(self, check):
        # simple, valid IUSE/REQUIRED_USE usage
        self.assertNoReport(check, self.mk_pkg(iuse="foo bar"))
        self.assertNoReport(check, self.mk_pkg(iuse="+foo", required_use="foo"))
        self.assertNoReport(check, self.mk_pkg(iuse="foo bar", required_use="foo? ( bar )"))

        # pkgs masked by the related profile aren't checked
        self.assertNoReport(
            self.mk_check(masks=(">=dev-util/diffball-8.0",)),
            self.mk_pkg(cpvstr="dev-util/diffball-8.0", iuse="foo bar", required_use="bar"),
        )

        # unsatisfied REQUIRED_USE
        r = self.assertReport(check, self.mk_pkg(iuse="foo bar", required_use="bar"))
        assert isinstance(r, metadata.RequiredUseDefaults)
        assert r.keyword == "x86"
        assert r.profile == "default/linux/x86"
        assert r.use == ()
        assert str(r.required_use) == "bar"

        # at-most-one-of
        self.assertNoReport(
            check, self.mk_pkg(eapi="5", iuse="foo bar", required_use="?? ( foo bar )")
        )
        self.assertNoReport(
            check, self.mk_pkg(eapi="5", iuse="+foo bar", required_use="?? ( foo bar )")
        )
        self.assertNoReport(
            check, self.mk_pkg(eapi="5", iuse="foo +bar", required_use="?? ( foo bar )")
        )
        r = self.assertReport(
            check, self.mk_pkg(eapi="5", iuse="+foo +bar", required_use="?? ( foo bar )")
        )
        assert isinstance(r, metadata.RequiredUseDefaults)
        assert r.use == ("bar", "foo")
        assert str(r.required_use) == "at-most-one-of ( foo bar )"

        # exactly-one-of
        self.assertNoReport(check, self.mk_pkg(iuse="+foo bar", required_use="^^ ( foo bar )"))
        self.assertNoReport(check, self.mk_pkg(iuse="foo +bar", required_use="^^ ( foo bar )"))
        self.assertReport(check, self.mk_pkg(iuse="foo bar", required_use="^^ ( foo bar )"))
        r = self.assertReport(check, self.mk_pkg(iuse="+foo +bar", required_use="^^ ( foo bar )"))
        assert isinstance(r, metadata.RequiredUseDefaults)
        assert r.use == ("bar", "foo")
        assert str(r.required_use) == "exactly-one-of ( foo bar )"

        # all-of
        self.assertNoReport(check, self.mk_pkg(iuse="foo bar baz", required_use="foo? ( bar baz )"))
        self.assertNoReport(
            check, self.mk_pkg(iuse="+foo +bar +baz", required_use="foo? ( bar baz )")
        )
        self.assertReports(check, self.mk_pkg(iuse="+foo bar baz", required_use="foo? ( bar baz )"))
        self.assertReport(check, self.mk_pkg(iuse="+foo +bar baz", required_use="foo? ( bar baz )"))
        r = self.assertReport(
            check, self.mk_pkg(iuse="+foo bar +baz", required_use="foo? ( bar baz )")
        )
        assert isinstance(r, metadata.RequiredUseDefaults)
        assert r.use == ("baz", "foo")
        # TODO: fix this output to show both required USE flags
        assert str(r.required_use) == "bar"

        # any-of
        self.assertNoReport(
            check, self.mk_pkg(iuse="foo bar baz", required_use="foo? ( || ( bar baz ) )")
        )
        self.assertNoReport(
            check, self.mk_pkg(iuse="+foo +bar baz", required_use="foo? ( || ( bar baz ) )")
        )
        self.assertNoReport(
            check, self.mk_pkg(iuse="+foo bar +baz", required_use="foo? ( || ( bar baz ) )")
        )
        self.assertNoReport(
            check, self.mk_pkg(iuse="+foo +bar +baz", required_use="foo? ( || ( bar baz ) )")
        )
        r = self.assertReport(
            check, self.mk_pkg(iuse="+foo bar baz", required_use="foo? ( || ( bar baz ) )")
        )
        assert isinstance(r, metadata.RequiredUseDefaults)
        assert r.use == ("foo",)
        assert str(r.required_use) == "( bar || baz )"


def use_based():
    # hidden to keep the test runner from finding it
    class UseBased(IUSE_Options):
        def test_required_addons(self):
            assert addons.UseAddon in self.check_kls.required_addons

        def mk_check(self, *args, options=None, **kwargs):
            options = options if options is not None else {}
            options = self.get_options(**options)
            profiles = [misc.FakeProfile(iuse_effective=["x86"])]
            use_addon = addons.UseAddon(options)
            check = self.check_kls(options, *args, use_addon=use_addon, **kwargs)
            return check

    return UseBased


class _TestRestrictPropertiesCheck(use_based(), misc.ReportTestCase):
    def mk_pkg(self, restrict="", properties="", iuse=""):
        return misc.FakePkg(
            "dev-util/diffball-2.7.1",
            data={"IUSE": iuse, "RESTRICT": restrict, "PROPERTIES": properties},
        )

    def test_no_allowed(self):
        # repo or its masters don't define any allowed values so anything goes
        check = self.mk_check()
        self.assertNoReport(check, self.mk_pkg(**{self.check_kls._attr: "foo"}))
        self.assertNoReport(
            check, self.mk_pkg(**{self.check_kls._attr: "foo? ( bar )", "iuse": "foo"})
        )

    def test_allowed(self):
        check = self.mk_check(options={self.check_kls._attr: ("foo",)})
        # allowed
        self.assertNoReport(check, self.mk_pkg(**{self.check_kls._attr: "foo"}))

        # unknown
        r = self.assertReport(check, self.mk_pkg(**{self.check_kls._attr: "bar"}))
        assert isinstance(r, self.check_kls._unknown_result_cls)
        assert f'unknown {self.check_kls._attr.upper()}="bar"' in str(r)

        # unknown multiple, conditional
        pkg = self.mk_pkg(**{self.check_kls._attr: "baz? ( foo bar boo )", "iuse": "baz"})
        r = self.assertReport(check, pkg)
        assert isinstance(r, self.check_kls._unknown_result_cls)
        assert f'unknown {self.check_kls._attr.upper()}="bar boo"' in str(r)

    def test_unstated_iuse(self):
        check = self.mk_check()
        # no IUSE
        self.assertNoReport(check, self.mk_pkg(**{self.check_kls._attr: "foo"}))
        # conditional with IUSE defined
        self.assertNoReport(
            check, self.mk_pkg(**{self.check_kls._attr: "foo? ( bar )", "iuse": "foo"})
        )
        # conditional missing IUSE
        r = self.assertReport(check, self.mk_pkg(**{self.check_kls._attr: "foo? ( bar )"}))
        assert isinstance(r, addons.UnstatedIuse)
        assert "unstated flag: [ foo ]" in str(r)
        # multiple missing IUSE
        r = self.assertReport(
            check, self.mk_pkg(**{self.check_kls._attr: "foo? ( bar ) boo? ( blah )"})
        )
        assert isinstance(r, addons.UnstatedIuse)
        assert "unstated flags: [ boo, foo ]" in str(r)


class TestRestrictCheck(_TestRestrictPropertiesCheck):
    check_kls = metadata.RestrictCheck


class TestPropertiesCheck(_TestRestrictPropertiesCheck):
    check_kls = metadata.PropertiesCheck


class _TestRestrictPropertiesCheck(use_based(), misc.ReportTestCase):
    check_kls = metadata.RestrictCheck
    attr = None
    unknown_result_cls = None


class TestRestrictTestCheck(misc.ReportTestCase):
    check_kls = metadata.RestrictTestCheck
    check = metadata.RestrictTestCheck(None)

    def mk_pkg(self, iuse="", restrict=""):
        return misc.FakePkg("dev-util/diffball-2.7.1", data={"IUSE": iuse, "RESTRICT": restrict})

    def test_empty_restrict(self):
        self.assertNoReport(self.check, self.mk_pkg())

    def test_specified_restrict(self):
        self.assertNoReport(self.check, self.mk_pkg(iuse="test", restrict="!test? ( test )"))

        # unconditional restriction is fine too
        self.assertNoReport(self.check, self.mk_pkg(iuse="test", restrict="test"))
        self.assertNoReport(self.check, self.mk_pkg(restrict="test"))
        # more RESTRICTs
        self.assertNoReport(
            self.check,
            self.mk_pkg(iuse="foo test", restrict="foo? ( strip ) !test? ( test ) bindist"),
        )

    def test_missing_restrict(self):
        data = (
            ("test", ""),  # missing entirely
            ("foo test", "!foo? ( test )"),  # 'test' present in other condition
            (
                "foo test",
                "!foo? ( !test? ( test ) )",
            ),  # correct restriction inside another condition
            ("test", "test? ( test )"),  # USE condition gotten the other way around
        )
        for iuse, restrict in data:
            r = self.assertReport(self.check, self.mk_pkg(iuse=iuse, restrict=restrict))
            assert isinstance(r, metadata.MissingTestRestrict)
            assert 'RESTRICT="!test? ( test )"' in str(r)


class TestLicenseCheck(use_based(), misc.ReportTestCase):
    check_kls = metadata.LicenseCheck

    def mk_check(self, licenses=(), **kwargs):
        self.repo = FakeRepo(repo_id="test", licenses=licenses)
        options = self.get_options(**kwargs)
        use_addon = addons.UseAddon(options)
        check = self.check_kls(options, use_addon=use_addon)
        return check

    def mk_pkg(self, license="", iuse=""):
        return FakePkg(
            "dev-util/diffball-2.7.1", data={"LICENSE": license, "IUSE": iuse}, repo=self.repo
        )

    def test_malformed(self):
        r = self.assertReport(self.mk_check(), self.mk_pkg("|| ("))
        assert isinstance(r, metadata.InvalidLicense)
        assert r.attr == "license"

    def test_empty(self):
        r = self.assertReport(self.mk_check(), self.mk_pkg())
        assert isinstance(r, metadata.MissingLicense)

    def test_unstated_iuse(self):
        chk = self.mk_check(licenses=("BSD",))

        # no IUSE
        self.assertNoReport(chk, self.mk_pkg("BSD"))

        # conditional URI with related IUSE
        pkg = self.mk_pkg(license="foo? ( BSD )", iuse="foo")
        self.assertNoReport(chk, pkg)

        # conditional URI with missing IUSE
        pkg = self.mk_pkg(license="foo? ( BSD )")
        r = self.assertReport(chk, pkg)
        assert isinstance(r, addons.UnstatedIuse)
        assert "unstated flag: [ foo ]" in str(r)

    def test_single_missing(self):
        r = self.assertReport(self.mk_check(), self.mk_pkg("foo"))
        assert isinstance(r, metadata.UnknownLicense)
        assert r.licenses == ("foo",)

    def test_multiple_existing(self):
        chk = self.mk_check(["foo", "foo2"])
        self.assertNoReport(chk, self.mk_pkg("foo"))
        self.assertNoReport(chk, self.mk_pkg("foo", "foo2"))

    def test_multiple_missing(self):
        chk = self.mk_check(["foo", "foo2"])
        r = self.assertReport(chk, self.mk_pkg("|| ( foo foo3 foo4 )"))
        assert isinstance(r, metadata.UnknownLicense)
        assert r.licenses == ("foo3", "foo4")

    def test_unlicensed_categories(self):
        check = self.mk_check(["foo"])
        for category in self.check_kls.unlicensed_categories:
            for license in ("foo", ""):
                pkg = FakePkg(
                    f"{category}/diffball-2.7.1", data={"LICENSE": license}, repo=self.repo
                )
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
                FakePkg("dev-libs/foo-0", slot="0"),
                FakePkg("dev-libs/foo-1", slot="1"),
                FakePkg("dev-libs/bar-2", slot="2"),
            )
        self.repo = FakeRepo(pkgs=pkgs, repo_id="test")
        options = self.get_options(**kwargs)
        use_addon = addons.UseAddon(options)
        check = self.check_kls(options, use_addon=use_addon)
        return check

    def mk_pkg(self, eapi="5", rdepend="", depend=""):
        return FakePkg(
            "dev-util/diffball-2.7.1",
            eapi=eapi,
            data={"RDEPEND": rdepend, "DEPEND": depend},
            repo=self.repo,
        )

    def test_flagged_deps(self):
        for dep_str in ("dev-libs/foo", "dev-libs/foo[bar]"):
            for eapi_str, eapi_obj in eapi.EAPI.known_eapis.items():
                if eapi_obj.options.sub_slotting:
                    r = self.assertReport(
                        self.mk_check(), self.mk_pkg(eapi=eapi_str, rdepend=dep_str, depend=dep_str)
                    )
                    assert isinstance(r, metadata.MissingSlotDep)
                    assert "matches more than one slot: [ 0, 1 ]" in str(r)

    def test_skipped_deps(self):
        for dep_str in (
            "!dev-libs/foo",
            "!!dev-libs/foo",  # blockers
            "~dev-libs/foo-0",
            "~dev-libs/foo-1",  # version limited to single slots
            "dev-libs/foo:0",
            "dev-libs/foo:1",  # slotted
            "dev-libs/foo:*",
            "dev-libs/foo:=",  # slot operators
        ):
            for eapi_str, eapi_obj in eapi.EAPI.known_eapis.items():
                if eapi_obj.options.sub_slotting:
                    self.assertNoReport(
                        self.mk_check(), self.mk_pkg(eapi=eapi_str, rdepend=dep_str, depend=dep_str)
                    )

    def test_no_deps(self):
        self.assertNoReport(self.mk_check(), self.mk_pkg())

    def test_single_slot_dep(self):
        self.assertNoReport(
            self.mk_check(), self.mk_pkg(rdepend="dev-libs/bar", depend="dev-libs/bar")
        )


class TestDependencyCheck(use_based(), misc.ReportTestCase):
    check_kls = metadata.DependencyCheck

    def mk_pkg(self, attr, depset="", eapi="0", iuse=""):
        eapi_attr_map = {"BDEPEND": "7", "IDEPEND": "8"}
        eapi = eapi_attr_map.get(attr, eapi)
        return misc.FakePkg(
            "dev-util/diffball-2.7.1", data={"EAPI": eapi, "IUSE": iuse, attr: depset}
        )

    def mk_check(self, pkgs=None, **kwargs):
        if pkgs is None:
            pkgs = (
                FakePkg("dev-libs/foo-0", slot="0", iuse=("bar",)),
                FakePkg("dev-libs/foo-1", slot="1", iuse=("bar", "baz")),
                FakePkg("dev-libs/bar-2", slot="2"),
            )
        kwargs["search_repo"] = FakeRepo(pkgs=pkgs, repo_id="test")
        return super().mk_check(options=kwargs)

    # pull the set of dependency attrs from the most recent EAPI
    dep_attrs = sorted(list(eapi.EAPI.known_eapis.values())[-1].dep_keys)

    @pytest.mark.parametrize("attr", dep_attrs)
    def test_depset(self, attr):
        chk = self.mk_check()
        mk_pkg = partial(self.mk_pkg, attr)

        # various regular depsets
        self.assertNoReport(chk, mk_pkg())
        self.assertNoReport(chk, mk_pkg("dev-util/foo"))
        self.assertNoReport(chk, mk_pkg("|| ( dev-util/foo ) dev-foo/bugger "))
        if attr == "RDEPEND":
            self.assertNoReport(chk, mk_pkg("!dev-util/blah"))
        else:
            r = self.assertReport(chk, mk_pkg("!dev-util/blah"))
            assert isinstance(r, metadata.MisplacedWeakBlocker)

        # invalid depset syntax
        r = self.assertReport(chk, mk_pkg("|| ("))
        assert isinstance(r, getattr(metadata, f"Invalid{attr.lower().capitalize()}"))

        # pkg blocking itself
        r = self.assertReport(chk, mk_pkg("!dev-util/diffball"))
        assert isinstance(r, metadata.BadDependency)
        assert "blocks itself" in str(r)
        assert f'{attr.upper()}="!dev-util/diffball"' in str(r)

        # check for := in || () blocks
        pkg = mk_pkg(eapi="5", depset="|| ( dev-libs/foo:= dev-libs/bar )")
        r = self.assertReport(chk, pkg)
        assert isinstance(r, metadata.BadDependency)
        assert "= slot operator used inside || block" in str(r)
        assert f'{attr.upper()}="dev-libs/foo:="' in str(r)

        # multiple := atoms in || () blocks
        pkg = mk_pkg(eapi="5", depset="|| ( dev-libs/foo:= dev-libs/bar:= )")
        reports = self.assertReports(chk, pkg)
        for r in reports:
            assert isinstance(r, metadata.BadDependency)
            assert "= slot operator used inside || block" in str(r)

        # check for := in blockers
        r = self.assertReport(chk, mk_pkg(eapi="5", depset="!dev-libs/foo:="))
        assert isinstance(r, metadata.BadDependency)
        assert "= slot operator used in blocker" in str(r)
        assert f'{attr.upper()}="!dev-libs/foo:="' in str(r)

        if attr == "PDEPEND":
            # check for := in PDEPEND
            r = self.assertReport(chk, mk_pkg(eapi="5", depset="dev-libs/foo:="))
            assert isinstance(r, metadata.BadDependency)
            assert "':=' operator" in str(r)
            assert f'{attr.upper()}="dev-libs/foo:="' in str(r)

        # check for missing package revisions
        self.assertNoReport(chk, mk_pkg("=dev-libs/foo-1-r0"))
        r = self.assertReport(chk, mk_pkg(eapi="6", depset="=dev-libs/foo-1"))
        assert isinstance(r, metadata.MissingPackageRevision)
        assert f'{attr.upper()}="=dev-libs/foo-1"' in str(r)

    @pytest.mark.parametrize("attr", dep_attrs)
    def test_depset_unstated_iuse(self, attr):
        chk = self.mk_check()
        mk_pkg = partial(self.mk_pkg, attr)

        # unstated IUSE
        r = self.assertReport(chk, mk_pkg(depset="foo? ( dev-libs/foo )"))
        assert isinstance(r, addons.UnstatedIuse)
        assert "unstated flag: [ foo ]" in str(r)
        # known IUSE
        self.assertNoReport(chk, mk_pkg(depset="foo? ( dev-libs/foo )", iuse="foo"))
        # multiple unstated IUSE
        r = self.assertReport(chk, mk_pkg(depset="foo? ( !bar? ( dev-libs/foo ) )"))
        assert isinstance(r, addons.UnstatedIuse)
        assert "unstated flags: [ bar, foo ]" in str(r)

    @pytest.mark.parametrize("attr", dep_attrs)
    def test_depset_missing_usedep_default(self, attr):
        chk = self.mk_check()
        mk_pkg = partial(self.mk_pkg, attr, iuse="foo bar baz blah")

        # USE flag exists on all matching pkgs
        self.assertNoReport(chk, mk_pkg(eapi="4", depset="dev-libs/foo[bar?]"))

        use_deps = (
            "foo(-)?",
            "!foo(-)?",
            "foo(+)?",
            "!foo(+)?",
            "foo(-)=",
            "!foo(-)=",
            "foo(+)=",
            "!foo(+)=",
            "-foo(-)",
            "-foo(+)",
        )
        for use_dep in use_deps:
            # USE flag doesn't exist but has proper default
            self.assertNoReport(chk, mk_pkg(eapi="4", depset=f"dev-libs/bar[{use_dep}]"))
            if attr == "RDEPEND":
                self.assertNoReport(chk, mk_pkg(eapi="4", depset=f"!dev-libs/bar[{use_dep}]"))
            else:
                r = self.assertReport(chk, mk_pkg(eapi="4", depset=f"!dev-libs/bar[{use_dep}]"))
                assert isinstance(r, metadata.MisplacedWeakBlocker)

        # result triggers when all matching pkgs don't have requested USE flag
        for dep in (
            "dev-libs/bar[foo?]",
            "dev-libs/bar[!foo?]",
            "dev-libs/bar[foo=]",
            "dev-libs/bar[!foo=]",
            "dev-libs/bar[-foo]",
            "|| ( dev-libs/foo[bar] dev-libs/bar[foo] )",
            "|| ( dev-libs/foo[bar] dev-libs/bar[-foo] )",
        ):
            r = self.assertReport(chk, mk_pkg(eapi="4", depset=dep))
            assert isinstance(r, metadata.MissingUseDepDefault)
            assert r.pkgs == ("dev-libs/bar-2",)
            assert r.flag == "foo"
            assert "USE flag 'foo' missing" in str(r)

        if attr == "RDEPEND":
            r = self.assertReport(chk, mk_pkg(eapi="4", depset="!dev-libs/bar[foo?]"))
            assert isinstance(r, metadata.MissingUseDepDefault)
            assert r.pkgs == ("dev-libs/bar-2",)
            assert r.flag == "foo"
            assert "USE flag 'foo' missing" in str(r)

        # USE flag missing on one of multiple matches
        r = self.assertReport(chk, mk_pkg(eapi="4", depset="dev-libs/foo[baz?]"))
        assert isinstance(r, metadata.MissingUseDepDefault)
        assert r.atom == "dev-libs/foo[baz?]"
        assert r.pkgs == ("dev-libs/foo-0",)
        assert r.flag == "baz"
        assert "USE flag 'baz' missing" in str(r)

        # USE flag missing on all matches
        r = self.assertReport(chk, mk_pkg(eapi="4", depset="dev-libs/foo[blah?]"))
        assert isinstance(r, metadata.MissingUseDepDefault)
        assert r.atom == "dev-libs/foo[blah?]"
        assert r.pkgs == ("dev-libs/foo-0", "dev-libs/foo-1")
        assert r.flag == "blah"
        assert "USE flag 'blah' missing" in str(r)


class TestOutdatedBlockersCheck(misc.ReportTestCase):
    check_kls = metadata.OutdatedBlockersCheck

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, tool, make_repo, make_git_repo):
        self.tool = tool
        self.cache_dir = str(tmp_path)

        # initialize parent repo
        self.parent_git_repo = make_git_repo()
        self.parent_repo = make_repo(self.parent_git_repo.path)
        self.parent_git_repo.add_all("initial commit")
        # create a stub pkg and commit it
        self.parent_repo.create_ebuild("cat/pkg-0")
        self.parent_git_repo.add_all("cat/pkg-0")

        # initialize child repo
        self.child_git_repo = make_git_repo()
        self.child_git_repo.run(["git", "remote", "add", "origin", self.parent_git_repo.path])
        self.child_git_repo.run(["git", "pull", "origin", "main"])
        self.child_git_repo.run(["git", "remote", "set-head", "origin", "main"])
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
            "scan",
            "-q",
            "--cache-dir",
            self.cache_dir,
            "--repo",
            self.child_repo.location,
        ]
        options, _ = self.tool.parse_args(args)
        return options

    def test_existent_blockers(self):
        self.child_repo.create_ebuild("cat/pkg-1", depend="!~cat/pkg-0")
        self.child_git_repo.add_all("cat/pkg: version bump to 1")
        self.child_repo.create_ebuild("cat/pkg-2", depend="!!~cat/pkg-0")
        self.child_git_repo.add_all("cat/pkg: version bump to 2")
        self.child_repo.create_ebuild("cat/pkg-3", depend="!!=cat/pkg-0*")
        self.child_git_repo.add_all("cat/pkg: version bump to 3")
        self.init_check()
        self.assertNoReport(self.check, self.source)

    def test_nonexistent_blockers(self):
        self.child_repo.create_ebuild("cat/pkg-1", depend="!nonexistent/pkg")
        self.child_git_repo.add_all("cat/pkg: version bump to 1")
        self.init_check()
        r = self.assertReport(self.check, self.source)
        expected = metadata.NonexistentBlocker("DEPEND", "!nonexistent/pkg", pkg=CPV("cat/pkg-1"))
        assert r == expected

    def test_outdated_blockers(self):
        self.parent_git_repo.remove_all("cat/pkg")
        self.child_git_repo.run(["git", "pull", "origin", "main"])
        self.child_repo.create_ebuild("cat/pkg-1", depend="!!=cat/pkg-0*")
        self.child_git_repo.add_all("cat/pkg: version bump to 1")

        # packages are not old enough to trigger any results
        for days in (0, 100, 365, 729):
            self.init_check(future=days)
            self.assertNoReport(self.check, self.source)

        # blocker was removed at least 4 years ago
        for days, years in ((1460, 4), (1825, 5)):
            self.init_check(future=days)
            r = self.assertReport(self.check, self.source)
            expected = metadata.OutdatedBlocker(
                "DEPEND", "!!=cat/pkg-0*", years, pkg=CPV("cat/pkg-1")
            )
            assert r == expected


class TestSrcUriCheck(use_based(), misc.ReportTestCase):
    check_kls = metadata.SrcUriCheck

    def mk_pkg(
        self, src_uri="", restrict="", default_chksums={"size": 100}, iuse="", disable_chksums=False
    ):
        class fake_repo:
            def __init__(self, default_chksums):
                if disable_chksums:
                    self.chksums = {}
                else:
                    self.chksums = {}.fromkeys(
                        {os.path.basename(x) for x in src_uri.split()}, default_chksums
                    )

            def _get_digests(self, pkg, allow_missing=False):
                return False, self.chksums

        class fake_parent:
            _parent_repo = fake_repo(default_chksums)

        return misc.FakePkg(
            "dev-util/diffball-2.7.1",
            data={"SRC_URI": src_uri, "IUSE": iuse, "RESTRICT": restrict},
            parent=fake_parent(),
        )

    def test_malformed(self):
        r = self.assertReport(self.mk_check(), self.mk_pkg("foon", disable_chksums=True))
        assert isinstance(r, metadata.InvalidSrcUri)
        assert r.attr == "fetchables"

    def test_regular_src_uri(self):
        chk = self.mk_check()
        # single file
        self.assertNoReport(chk, self.mk_pkg(src_uri="https://foon.com/foon-2.7.1.tar.gz"))
        # single file, multiple uris
        self.assertNoReport(
            chk, self.mk_pkg(src_uri="https://foo.com/a-0.tar.gz https://bar.com/a-0.tar.gz")
        )
        # multiple files, multiple uris
        self.assertNoReport(
            chk,
            self.mk_pkg(
                src_uri="""
                https://foo.com/a-0.tar.gz https://bar.com/a-0.tar.gz
                https://blah.org/b-1.zip https://boo.net/boo-10.tar.xz
            """
            ),
        )

    def test_unknown_mirror(self):
        chk = self.mk_check()

        # single mirror
        r = self.assertReport(chk, self.mk_pkg("mirror://foo/a-0.gz https://foo.com/a-0.gz"))
        assert isinstance(r, metadata.UnknownMirror)
        assert r.mirror == "foo"
        assert r.uri == "mirror://foo/a-0.gz"
        assert "unknown mirror 'foo'" in str(r)

        # multiple mirrors
        pkg = self.mk_pkg("mirror://foo/a-0.gz mirror://bar/a-0.gz https://foo.com/a-0.gz")
        reports = self.assertReports(chk, pkg)
        for mirror, r in zip(("bar", "foo"), sorted(reports, key=attrgetter("mirror"))):
            assert isinstance(r, metadata.UnknownMirror)
            assert r.mirror == mirror
            assert r.uri == f"mirror://{mirror}/a-0.gz"
            assert f"unknown mirror '{mirror}'" in str(r)

    def test_bad_filename(self):
        chk = self.mk_check()

        # PN filename
        r = self.assertReport(chk, self.mk_pkg("https://foon.com/diffball.tar.gz"))
        assert isinstance(r, metadata.BadFilename)
        assert r.filenames == ("diffball.tar.gz",)
        assert "bad filename: [ diffball.tar.gz ]" in str(r)

        # PV filename
        r = self.assertReport(chk, self.mk_pkg("https://foon.com/2.7.1.tar.gz"))
        assert isinstance(r, metadata.BadFilename)
        assert r.filenames == ("2.7.1.tar.gz",)
        assert "bad filename: [ 2.7.1.tar.gz ]" in str(r)

        # github-style PV filename
        r = self.assertReport(chk, self.mk_pkg("https://foon.com/v2.7.1.zip"))
        assert isinstance(r, metadata.BadFilename)
        assert r.filenames == ("v2.7.1.zip",)
        assert "bad filename: [ v2.7.1.zip ]" in str(r)

        # github-style commit snapshot filename
        r = self.assertReport(
            chk, self.mk_pkg("https://foon.com/cb230f01fb288a0b9f0fc437545b97d06c846bd3.tar.gz")
        )
        assert isinstance(r, metadata.BadFilename)

        # multiple bad filenames
        r = self.assertReport(
            chk, self.mk_pkg("https://foon.com/2.7.1.tar.gz https://foon.com/diffball.zip")
        )
        assert isinstance(r, metadata.BadFilename)
        assert r.filenames == ("2.7.1.tar.gz", "diffball.zip")
        assert "bad filenames: [ 2.7.1.tar.gz, diffball.zip ]" in str(r)

    def test_missing_uri(self):
        chk = self.mk_check()

        # mangled protocol
        r = self.assertReport(chk, self.mk_pkg("http:/foo/foo-0.tar.gz"))
        assert isinstance(r, metadata.MissingUri)
        assert r.filenames == ("http:/foo/foo-0.tar.gz",)
        assert "unfetchable file: 'http:/foo/foo-0.tar.gz'" in str(r)

        # no URI and RESTRICT doesn't contain 'fetch'
        r = self.assertReport(chk, self.mk_pkg("foon"))
        assert isinstance(r, metadata.MissingUri)
        assert r.filenames == ("foon",)
        assert "unfetchable file: 'foon'" in str(r)

        # no URI and RESTRICT contains 'fetch'
        self.assertNoReport(chk, self.mk_pkg("foon", restrict="fetch"))

        # conditional URI and conditional RESTRICT containing 'fetch'
        pkg = self.mk_pkg(src_uri="foo? ( bar )", iuse="foo", restrict="foo? ( fetch )")
        self.assertNoReport(chk, pkg)
        # negated
        pkg = self.mk_pkg(src_uri="!foo? ( bar )", iuse="foo", restrict="!foo? ( fetch )")
        self.assertNoReport(chk, pkg)
        # multi-level conditional
        pkg = self.mk_pkg(
            iuse="foo bar", src_uri="foo? ( bar? ( blah ) )", restrict="foo? ( bar? ( fetch ) )"
        )
        self.assertNoReport(chk, pkg)

    def test_unstated_iuse(self):
        chk = self.mk_check()

        # no IUSE
        self.assertNoReport(chk, self.mk_pkg("https://foo.com/foo-0.tar.gz"))

        # conditional URI with related IUSE
        pkg = self.mk_pkg(src_uri="foo? ( https://foo.com/foo-0.tar.gz )", iuse="foo")
        self.assertNoReport(chk, pkg)

        # conditional URI with missing IUSE
        pkg = self.mk_pkg(src_uri="foo? ( https://foo.com/foo-0.tar.gz )")
        r = self.assertReport(chk, pkg)
        assert isinstance(r, addons.UnstatedIuse)
        assert "unstated flag: [ foo ]" in str(r)

    def test_bad_proto(self):
        chk = self.mk_check()

        # verify valid protos.
        assert self.check_kls.valid_protos, "valid_protos needs to have at least one protocol"

        for proto in self.check_kls.valid_protos:
            self.assertNoReport(
                chk, self.mk_pkg(f"{proto}://dar.com/foon"), msg=f"testing valid proto {proto}"
            )

            bad_proto = f"{proto}x"

            r = self.assertReport(chk, self.mk_pkg(f"{bad_proto}://foon.com/foon"))
            assert isinstance(r, metadata.BadProtocol)
            assert bad_proto in str(r)
            assert f"{bad_proto}://foon.com/foon" in str(r)

            # check collapsing
            pkg = self.mk_pkg(f"{bad_proto}://foon.com/foon {bad_proto}://dar.com/foon")
            r = self.assertReport(chk, pkg)
            assert isinstance(r, metadata.BadProtocol)
            assert list(r.uris) == sorted(
                f"{bad_proto}://{x}/foon" for x in ("foon.com", "dar.com")
            )
            assert bad_proto in str(r)

    def test_tarball_available_github(self):
        chk = self.mk_check()
        uri = "https://github.com/foo/bar/archive/v1.2.3.zip"
        r = self.assertReport(chk, self.mk_pkg(uri))
        assert isinstance(r, metadata.TarballAvailable)
        assert r.uris == (uri,)
        assert "[ https://github.com/foo/bar/archive/v1.2.3.zip ]" in str(r)

    def test_tarball_available_gitlab(self):
        chk = self.mk_check()
        uri = "https://gitlab.com/foo/bar/-/archive/v1.2.3/bar-v1.2.3.zip"
        r = self.assertReport(chk, self.mk_pkg(uri))
        assert isinstance(r, metadata.TarballAvailable)
        assert r.uris == (uri,)
        assert "zip archive used when tarball available" in str(r)


class TestMissingUnpackerDepCheck(use_based(), misc.ReportTestCase):
    check_kls = metadata.MissingUnpackerDepCheck

    def mk_pkg(self, exts, eapi="7", **data):
        if isinstance(exts, str):
            exts = [exts]

        class fake_repo:
            def _get_digests(self, pkg, allow_missing=False):
                chksums = {f"diffball-2.7.1{ext}": {"size": 100} for ext in exts}
                return False, chksums

        data["SRC_URI"] = " ".join(f"https://foo.com/diffball-2.7.1{ext}" for ext in exts)
        return FakePkg("dev-util/diffball-2.7.1", data=data, eapi=eapi, repo=fake_repo())

    def test_with_system_dep(self):
        self.assertNoReport(self.mk_check(), self.mk_pkg(".tar.gz"))

    def test_keyword_output(self):
        # unpacker deps go in BDEPEND in EAPI >= 7
        r = self.assertReport(self.mk_check(), self.mk_pkg(".zip", eapi="7"))
        assert 'missing BDEPEND="app-arch/unzip"' in str(r)
        # and in DEPEND for EAPI < 7
        r = self.assertReport(self.mk_check(), self.mk_pkg(".zip", eapi="6"))
        assert 'missing DEPEND="app-arch/unzip"' in str(r)

    def test_without_dep(self):
        for ext, unpackers in self.check_kls.non_system_unpackers.items():
            pkg = self.mk_pkg(ext)
            r = self.assertReport(self.mk_check(), pkg)
            assert isinstance(r, metadata.MissingUnpackerDep)
            assert r.filenames == (f"diffball-2.7.1{ext}",)
            assert r.unpackers == tuple(sorted(map(str, self.check_kls.non_system_unpackers[ext])))

    def test_with_dep(self):
        for ext, unpackers in self.check_kls.non_system_unpackers.items():
            for dep_type in ("DEPEND", "BDEPEND"):
                for unpacker in unpackers:
                    for dep in (unpacker, f">={unpacker}-1"):
                        kwargs = {dep_type: dep}
                        pkg = self.mk_pkg(ext, **kwargs)
                        self.assertNoReport(self.mk_check(), pkg)

    def test_rar_with_or_dep(self):
        self.assertNoReport(
            self.mk_check(), self.mk_pkg(".rar", DEPEND="|| ( app-arch/rar app-arch/unrar )")
        )

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
                assert r.filenames == tuple(sorted(f"diffball-2.7.1{ext}" for ext in exts))
                assert r.unpackers == tuple(sorted(map(str, unpackers[0])))
            else:
                assert len(reports) == 2
                for i, r in enumerate(reports):
                    assert isinstance(r, metadata.MissingUnpackerDep)
                    assert r.filenames == (f"diffball-2.7.1{exts[i]}",)
                    assert r.unpackers == tuple(sorted(map(str, unpackers[i])))

    def test_with_multiple_unpackers_one_missing(self):
        r = self.assertReport(
            self.mk_check(), self.mk_pkg([".zip", ".7z"], DEPEND="app-arch/unzip")
        )
        assert isinstance(r, metadata.MissingUnpackerDep)
        assert r.filenames == (f"diffball-2.7.1.7z",)
        assert r.unpackers == ("app-arch/p7zip",)
