from pkgcheck.checks import acct

from pkgcore.test.misc import FakeRepo

from .. import misc

class TestAcctUser(misc.ReportTestCase):

    check_kls = acct.AcctCheck

    kind = 'user'

    def mk_check(self, pkgs):
        self.repo = FakeRepo(pkgs=pkgs, repo_id='test')
        check = self.check_kls(misc.Options(target_repo=self.repo))
        return check

    def mk_pkg(self, name, identifier, version=1, ebuild=None):
        class fake_parent:
            # NB: formally this should be a proper repo object but for our
            # purpose, any type suffices
            _parent_repo = 'test'

        if ebuild is None:
            ebuild = f'''
inherit acct-{self.kind}
ACCT_{self.kind.upper()}_ID="{identifier}"
'''
        return misc.FakePkg(f'acct-{self.kind}/{name}-{version}',
                            ebuild=ebuild, parent=fake_parent)

    def test_correct(self):
        pkgs = (self.mk_pkg('foo', 100),
                self.mk_pkg('bar', 200),
                self.mk_pkg('nobody', 65534))
        check = self.mk_check(pkgs)
        self.assertNoReport(check, pkgs)

    def test_invalid(self):
        pkgs = (self.mk_pkg('foo', None, ebuild='inherit acct-user\n'),)
        check = self.mk_check(pkgs)
        r = self.assertReport(check, pkgs)
        assert isinstance(r, acct.MissingAccountIdentifier)
        assert r.var == f'ACCT_{self.kind.upper()}_ID'

    def test_conflicting(self):
        pkgs = (self.mk_pkg('foo', 100),
                self.mk_pkg('bar', 100))
        check = self.mk_check(pkgs)
        r = self.assertReport(check, pkgs)
        assert isinstance(r, acct.ConflictingAccountIdentifier)
        assert r.kind == self.kind
        assert int(r.identifier) == 100

    def test_self_nonconflict(self):
        pkgs = (self.mk_pkg('foo', 100),
                self.mk_pkg('foo', 100, version=2))
        check = self.mk_check(pkgs)
        self.assertNoReport(check, pkgs)

    def test_dynamic_assignment_range(self):
        pkgs = (self.mk_pkg('foo', 500),)
        check = self.mk_check(pkgs)
        r = self.assertReport(check, pkgs)
        assert isinstance(r, acct.OutOfRangeAccountIdentifier)
        assert r.kind == self.kind
        assert int(r.identifier) == 500

    def test_sysadmin_assignment_range(self):
        pkgs = (self.mk_pkg('foo', 1000),)
        check = self.mk_check(pkgs)
        r = self.assertReport(check, pkgs)
        assert isinstance(r, acct.OutOfRangeAccountIdentifier)
        assert r.kind == self.kind
        assert int(r.identifier) == 1000

    def test_high_reserved(self):
        pkgs = (self.mk_pkg('foo', 65535),)
        check = self.mk_check(pkgs)
        r = self.assertReport(check, pkgs)
        assert isinstance(r, acct.OutOfRangeAccountIdentifier)
        assert r.kind == self.kind
        assert int(r.identifier) == 65535

    def test_nogroup(self):
        """Test that 65533 is not accepted for UID."""
        pkgs = (self.mk_pkg('nogroup', 65533),)
        check = self.mk_check(pkgs)
        r = self.assertReport(check, pkgs)
        assert isinstance(r, acct.OutOfRangeAccountIdentifier)
        assert r.kind == self.kind
        assert int(r.identifier) == 65533

    def test_nobody(self):
        pkgs = (self.mk_pkg('nobody', 65534),)
        check = self.mk_check(pkgs)
        self.assertNoReport(check, pkgs)


class TestAcctGroup(TestAcctUser):
    kind = 'group'

    def test_nogroup(self):
        """Test that 65533 is accepted for GID."""
        pkgs = (self.mk_pkg('nogroup', 65533),)
        check = self.mk_check(pkgs)
        self.assertNoReport(check, pkgs)
