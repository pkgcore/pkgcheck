import random

from pkgcheck import deprecated

from . import misc


def mk_pkg(ver, eclasses):
    return misc.FakePkg(
        f"dev-util/diffball-{ver}", data={"_eclasses_": {}.fromkeys(eclasses)})


class TestDeprecatedEclass(misc.ReportTestCase):

    check_kls = deprecated.DeprecatedEclassReport
    check = deprecated.DeprecatedEclassReport(None, None)

    def test_no_eclasses(self):
        self.assertNoReport(self.check, mk_pkg("0.7.1", []))

    def test_single_current_eclass(self):
        self.assertNoReport(self.check, mk_pkg("0.7.1", {'foobar': None}))

    def test_deprecated_no_replacement(self):
        eclass, replacement = next(
            (k, v) for k, v in self.check.blacklist.items() if v == None)
        eclasses = {eclass: replacement}
        r = self.assertReport(self.check, mk_pkg("0.1", eclasses))
        assert isinstance(r, deprecated.DeprecatedEclass)
        assert r.eclasses == tuple(eclasses.items())
        assert f"uses deprecated eclass: [ {eclass} (no replacement) ]" == str(r)

    def test_deprecated_with_replacement(self):
        eclass, replacement = next(
            (k, v) for k, v in self.check.blacklist.items() if v)
        eclasses = {eclass: replacement}
        r = self.assertReport(self.check, mk_pkg("0.1", eclasses))
        assert isinstance(r, deprecated.DeprecatedEclass)
        assert r.eclasses == tuple(eclasses.items())
        assert f"uses deprecated eclass: [ {eclass} (migrate to {replacement}) ]" == str(r)

    def test_deprecated_and_current(self):
        current = {str(x): None for x in range(3)}
        old = {x: self.check.blacklist[x] for x in random.sample(list(self.check.blacklist), 3)}
        eclasses = current.copy()
        eclasses.update(old)
        pkg = mk_pkg("0.1", eclasses)
        assert pkg.inherited == tuple(sorted(eclasses))
        r = self.assertReport(self.check, pkg)
        assert r.eclasses == tuple(sorted(old.items()))

    def test_all_known_deprecated(self):
        r = self.assertReport(self.check, mk_pkg("0.1", self.check.blacklist))
        assert isinstance(r, deprecated.DeprecatedEclass)
        assert r.eclasses == tuple(sorted(self.check.blacklist.items()))
