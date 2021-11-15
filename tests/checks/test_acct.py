from pkgcheck.checks import acct
from pkgcore.test.misc import FakeRepo
from snakeoil.cli import arghparse

from .. import misc


class TestAcctUser(misc.ReportTestCase):

    check_kls = acct.AcctCheck

    kind = 'user'

    def mk_check(self, pkgs):
        self.repo = FakeRepo(pkgs=pkgs, repo_id='test')
        check = self.check_kls(arghparse.Namespace(target_repo=self.repo, gentoo_repo=True))
        return check

    def mk_pkg(self, name, identifier, version=1, ebuild=None):
        if ebuild is None:
            ebuild = f'''
inherit acct-{self.kind}
ACCT_{self.kind.upper()}_ID="{identifier}"
'''
        return misc.FakePkg(f'acct-{self.kind}/{name}-{version}', ebuild=ebuild)

    def test_unmatching_pkgs(self):
        pkgs = (misc.FakePkg('dev-util/foo-0'),
                misc.FakePkg('dev-util/bar-1'))
        check = self.mk_check(pkgs)
        self.assertNoReport(check, pkgs)

    def test_correct_ids(self):
        pkgs = (self.mk_pkg('foo', 100),
                self.mk_pkg('bar', 200),
                self.mk_pkg('nobody', 65534))
        check = self.mk_check(pkgs)
        self.assertNoReport(check, pkgs)

    def test_missing_ids(self):
        pkg = self.mk_pkg('foo', None, ebuild='inherit acct-user\n')
        check = self.mk_check((pkg,))
        r = self.assertReport(check, pkg)
        assert isinstance(r, acct.MissingAccountIdentifier)
        assert r.var == f'ACCT_{self.kind.upper()}_ID'
        assert r.var in str(r)

    def test_conflicting_ids(self):
        pkgs = (self.mk_pkg('foo', 100),
                self.mk_pkg('bar', 100))
        check = self.mk_check(pkgs)
        r = self.assertReport(check, pkgs)
        assert isinstance(r, acct.ConflictingAccountIdentifiers)
        assert r.kind == self.kind
        assert r.identifier == 100
        assert r.pkgs == (f'acct-{self.kind}/bar-1', f'acct-{self.kind}/foo-1')
        assert f'conflicting {self.kind} id 100 usage: ' in str(r)

    def test_self_nonconflicting_ids(self):
        pkgs = (self.mk_pkg('foo', 100),
                self.mk_pkg('foo', 100, version=2))
        check = self.mk_check(pkgs)
        self.assertNoReport(check, pkgs)

    def test_dynamic_assignment_range(self):
        pkg = self.mk_pkg('foo', 750)
        check = self.mk_check((pkg,))
        r = self.assertReport(check, pkg)
        assert isinstance(r, acct.OutsideRangeAccountIdentifier)
        assert r.kind == self.kind
        assert r.identifier == 750
        assert f'{self.kind} id 750 outside permitted' in str(r)

    def test_sysadmin_assignment_range(self):
        pkg = self.mk_pkg('foo', 1000)
        check = self.mk_check((pkg,))
        r = self.assertReport(check, pkg)
        assert isinstance(r, acct.OutsideRangeAccountIdentifier)
        assert r.kind == self.kind
        assert r.identifier == 1000

    def test_high_reserved(self):
        pkg = self.mk_pkg('foo', 65535)
        check = self.mk_check((pkg,))
        r = self.assertReport(check, pkg)
        assert isinstance(r, acct.OutsideRangeAccountIdentifier)
        assert r.kind == self.kind
        assert r.identifier == 65535

    def test_nogroup(self):
        """Test that 65533 is not accepted for UID."""
        pkg = self.mk_pkg('nogroup', 65533)
        check = self.mk_check((pkg,))
        r = self.assertReport(check, pkg)
        assert isinstance(r, acct.OutsideRangeAccountIdentifier)
        assert r.kind == self.kind
        assert r.identifier == 65533

    def test_nobody(self):
        pkg = self.mk_pkg('nobody', 65534)
        check = self.mk_check((pkg,))
        self.assertNoReport(check, pkg)


class TestAcctGroup(TestAcctUser):
    kind = 'group'

    def test_nogroup(self):
        """Test that 65533 is accepted for GID."""
        pkg = self.mk_pkg('nogroup', 65533)
        check = self.mk_check((pkg,))
        self.assertNoReport(check, pkg)
