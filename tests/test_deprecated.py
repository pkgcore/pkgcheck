import random

from pkgcheck import deprecated
from pkgcheck.test import misc


class TestDeprecatedEclass(misc.ReportTestCase):

    check_kls = deprecated.DeprecatedEclassReport

    def mk_pkg(self, ver, eclasses):
        return misc.FakePkg(
            f"dev-util/diffball-{ver}",
            data={"_eclasses_": {}.fromkeys(eclasses)})

    def test_it(self):
        check = deprecated.DeprecatedEclassReport(None, None)

        # no eclasses
        self.assertNoReport(check, self.mk_pkg("0.7.1", []))

        # one non-deprecated eclass
        self.assertNoReport(check, self.mk_pkg("0.7.1", {'foobar': None}))

        # deprecated eclass with no replacement
        eclass, replacement = next(
            (k, v) for k, v in check.blacklist.items() if v == None)
        eclasses = {eclass: replacement}
        r = self.assertReport(check, self.mk_pkg("0.1", eclasses))
        assert isinstance(r, deprecated.DeprecatedEclass)
        assert r.eclasses == tuple(eclasses.items())
        assert f"uses deprecated eclass: [ {eclass} (no replacement) ]" == str(r)

        # deprecated eclass with replacement
        eclass, replacement = next(
            (k, v) for k, v in check.blacklist.items() if v)
        eclasses = {eclass: replacement}
        r = self.assertReport(check, self.mk_pkg("0.1", eclasses))
        assert isinstance(r, deprecated.DeprecatedEclass)
        assert r.eclasses == tuple(eclasses.items())
        assert f"uses deprecated eclass: [ {eclass} (migrate to {replacement}) ]" == str(r)

        # mix of deprecated and non-deprecated eclasses
        current = {str(x): None for x in range(3)}
        old = {x: check.blacklist[x] for x in random.sample(list(check.blacklist), 3)}
        eclasses = current.copy()
        eclasses.update(old)
        pkg = self.mk_pkg("0.1", eclasses)
        assert pkg.inherited == tuple(sorted(eclasses))
        r = self.assertReport(check, pkg)
        assert r.eclasses == tuple(sorted(old.items()))

        # all known, deprecated eclasses
        r = self.assertReport(check, self.mk_pkg("0.1", check.blacklist))
        assert isinstance(r, deprecated.DeprecatedEclass)
        assert r.eclasses == tuple(sorted(check.blacklist.items()))
