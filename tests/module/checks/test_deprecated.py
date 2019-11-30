import random

from pkgcheck.checks import deprecated

from .. import misc


def mk_pkg(ver, fake_src, eapi='0'):
    return misc.FakePkg(f"dev-util/diffball-{ver}", data={'EAPI': eapi}, ebuild=fake_src)


class TestDeprecatedEclass(misc.ReportTestCase):

    check_kls = deprecated.DeprecatedEclassCheck
    check = deprecated.DeprecatedEclassCheck(None)

    def test_no_eclasses(self):
        fake_src = """
            # This is a fake ebuild
            # That's it for now
        """
        self.assertNoReport(self.check, mk_pkg("0.7.1", fake_src))

    def test_single_current_eclass(self):
        fake_src = """
            # This is a fake ebuild
            EAPI=7

            inherit git-r3
        """
        self.assertNoReport(self.check, mk_pkg("0.7.1", fake_src, eapi='7'))

    def test_deprecated_no_replacement(self):
        eclass = next(
            k for k, v in self.check.blacklist.items() if v == None)

        fake_src = f"""
            # This is a fake ebuild
            EAPI=2
            inherit {eclass}
        """

        r = self.assertReport(self.check, mk_pkg("0.1", fake_src, eapi='2'))
        assert isinstance(r, deprecated.DeprecatedEclass)
        assert r.eclasses == ((eclass, None),)
        assert f"uses deprecated eclass: [ {eclass} (no replacement) ]" == str(r)

    def test_deprecated_with_replacement(self):
        eclass, replacement = next(
            (k, v) for k, v in self.check.blacklist.items() if isinstance(v, str))

        fake_src = f"""
            # This is a fake ebuild
            EAPI=4

            inherit {eclass}
        """

        r = self.assertReport(self.check, mk_pkg("0.1", fake_src, eapi='4'))
        assert isinstance(r, deprecated.DeprecatedEclass)
        assert r.eclasses == ((eclass, replacement),)
        assert f"uses deprecated eclass: [ {eclass} (migrate to {replacement}) ]" == str(r)

    def test_deprecated_and_current(self):
        eclass, replacement = next(
            (k, v) for k, v in self.check.blacklist.items() if isinstance(v, str))

        fake_src = f"""
            # This is a fake ebuild
            EAPI=1

            inherit git-r3 {eclass}
        """

        r = self.assertReport(self.check, mk_pkg("0.1", fake_src, eapi='1'))
        assert isinstance(r, deprecated.DeprecatedEclass)
        assert r.eclasses == ((eclass, replacement),)
        assert f"uses deprecated eclass: [ {eclass} (migrate to {replacement}) ]" == str(r)

    def test_deprecated_conditional(self):
        fake_src = f"""
            # This is a fake ebuild
            EAPI=7

            inherit versionator
        """

        r = self.assertReport(self.check, mk_pkg("0.1", fake_src, eapi='7'))
        assert isinstance(r, deprecated.DeprecatedEclass)
        assert 'versionator' in str(r)

    def test_nondeprecated_conditional(self):
        fake_src = f"""
            # This is a fake ebuild
            EAPI=6

            inherit versionator
        """

        self.assertNoReport(self.check, mk_pkg("0.1", fake_src, eapi='6'))
