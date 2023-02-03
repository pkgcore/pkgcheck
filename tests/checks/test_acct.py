import textwrap

import pytest
from pkgcheck.checks import acct, SkipCheck
from pkgcore.test.misc import FakeRepo
from snakeoil.cli import arghparse

from .. import misc


class TestAcctUser(misc.ReportTestCase):
    check_kls = acct.AcctCheck

    kind = "user"

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        (metadata := tmp_path / "metadata").mkdir()
        (metadata / "qa-policy.conf").write_text(
            textwrap.dedent(
                """\
                    [user-group-ids]
                    uid-range = 0-749,65534
                    gid-range = 0-749,65533,65534
                """
            )
        )
        self.location = str(tmp_path)

    def mk_check(self, pkgs):
        repo = FakeRepo(pkgs=pkgs, repo_id="test", location=self.location)
        check = self.check_kls(arghparse.Namespace(target_repo=repo, gentoo_repo=True))
        return check

    def mk_pkg(self, name, identifier, version=1, ebuild=None):
        if ebuild is None:
            ebuild = textwrap.dedent(
                f"""\
                    inherit acct-{self.kind}
                    ACCT_{self.kind.upper()}_ID="{identifier}"
                """
            )
        return misc.FakePkg(f"acct-{self.kind}/{name}-{version}", ebuild=ebuild)

    def test_unmatching_pkgs(self):
        pkgs = (misc.FakePkg("dev-util/foo-0"), misc.FakePkg("dev-util/bar-1"))
        check = self.mk_check(pkgs)
        self.assertNoReport(check, pkgs)

    def test_correct_ids(self):
        pkgs = (
            self.mk_pkg("foo", 100),
            self.mk_pkg("bar", 200),
            self.mk_pkg("test", 749),
            self.mk_pkg("nobody", 65534),
        )
        check = self.mk_check(pkgs)
        self.assertNoReport(check, pkgs)

    def test_missing_ids(self):
        pkg = self.mk_pkg("foo", None, ebuild="inherit acct-user\n")
        check = self.mk_check((pkg,))
        r = self.assertReport(check, pkg)
        assert isinstance(r, acct.MissingAccountIdentifier)
        assert r.var == f"ACCT_{self.kind.upper()}_ID"
        assert r.var in str(r)

    def test_conflicting_ids(self):
        pkgs = (self.mk_pkg("foo", 100), self.mk_pkg("bar", 100))
        check = self.mk_check(pkgs)
        r = self.assertReport(check, pkgs)
        assert isinstance(r, acct.ConflictingAccountIdentifiers)
        assert r.kind == self.kind
        assert r.identifier == 100
        assert r.pkgs == (f"acct-{self.kind}/bar-1", f"acct-{self.kind}/foo-1")
        assert f"conflicting {self.kind} id 100 usage: " in str(r)

    def test_self_nonconflicting_ids(self):
        pkgs = (self.mk_pkg("foo", 100), self.mk_pkg("foo", 100, version=2))
        check = self.mk_check(pkgs)
        self.assertNoReport(check, pkgs)

    def test_dynamic_assignment_range(self):
        pkg = self.mk_pkg("foo", 750)
        check = self.mk_check((pkg,))
        r = self.assertReport(check, pkg)
        assert isinstance(r, acct.OutsideRangeAccountIdentifier)
        assert r.kind == self.kind
        assert r.identifier == 750
        assert f"{self.kind} id 750 outside permitted" in str(r)

    def test_sysadmin_assignment_range(self):
        pkg = self.mk_pkg("foo", 1000)
        check = self.mk_check((pkg,))
        r = self.assertReport(check, pkg)
        assert isinstance(r, acct.OutsideRangeAccountIdentifier)
        assert r.kind == self.kind
        assert r.identifier == 1000

    def test_high_reserved(self):
        pkg = self.mk_pkg("foo", 65535)
        check = self.mk_check((pkg,))
        r = self.assertReport(check, pkg)
        assert isinstance(r, acct.OutsideRangeAccountIdentifier)
        assert r.kind == self.kind
        assert r.identifier == 65535

    def test_nogroup(self):
        """Test that 65533 is not accepted for UID."""
        pkg = self.mk_pkg("nogroup", 65533)
        check = self.mk_check((pkg,))
        r = self.assertReport(check, pkg)
        assert isinstance(r, acct.OutsideRangeAccountIdentifier)
        assert r.kind == self.kind
        assert r.identifier == 65533

    def test_nobody(self):
        pkg = self.mk_pkg("nobody", 65534)
        check = self.mk_check((pkg,))
        self.assertNoReport(check, pkg)


class TestAcctGroup(TestAcctUser):
    kind = "group"

    def test_nogroup(self):
        """Test that 65533 is accepted for GID."""
        pkg = self.mk_pkg("nogroup", 65533)
        check = self.mk_check((pkg,))
        self.assertNoReport(check, pkg)


class TestQaPolicyValidation(misc.ReportTestCase):
    def mk_check(self, tmp_path, content):
        if content:
            (metadata := tmp_path / "metadata").mkdir()
            (metadata / "qa-policy.conf").write_text(textwrap.dedent(content))
        repo = FakeRepo(repo_id="test", location=str(tmp_path))
        return acct.AcctCheck(arghparse.Namespace(target_repo=repo, gentoo_repo=True))

    def test_missing_qa_policy(self, tmp_path):
        with pytest.raises(SkipCheck, match="failed loading 'metadata/qa-policy.conf'"):
            self.mk_check(tmp_path, None)

    def test_missing_section(self, tmp_path):
        with pytest.raises(SkipCheck, match="missing section user-group-ids"):
            self.mk_check(
                tmp_path,
                """\
                [random]
                x = 5
            """,
            )

    def test_missing_config(self, tmp_path):
        with pytest.raises(SkipCheck, match="missing value for gid-range"):
            self.mk_check(
                tmp_path,
                """\
                [user-group-ids]
                uid-range = 0-749
            """,
            )

    @pytest.mark.parametrize(
        "value",
        (
            "start-end",
            "0-749-1500",
            ",150",
        ),
    )
    def test_invalid_value(self, tmp_path, value):
        with pytest.raises(SkipCheck, match="invalid value for uid-range"):
            self.mk_check(
                tmp_path,
                f"""\
                [user-group-ids]
                uid-range = {value}
                gid-range = 0-749
            """,
            )
