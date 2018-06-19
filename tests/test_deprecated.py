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

        # one deprecated eclass
        eclasses = dict([next(iter(check.blacklist.items()))])
        r = self.assertReport(check, self.mk_pkg("0.1", eclasses))
        self.assertIsInstance(r, deprecated.DeprecatedEclass)
        self.assertEqual(r.eclasses, tuple(eclasses.items()))

        # mix of deprecated and non-deprecated eclasses
        current = {str(x): None for x in range(3)}
        old = {x: check.blacklist[x] for x in random.sample(list(check.blacklist), 3)}
        eclasses = current.copy()
        eclasses.update(old)
        pkg = self.mk_pkg("0.1", eclasses)
        self.assertEqual(pkg.inherited, tuple(sorted(eclasses)))
        r = self.assertReport(check, pkg)
        self.assertEqual(r.eclasses, tuple(sorted(old.items())))

        # all known, deprecated eclasses
        r = self.assertReport(check, self.mk_pkg("0.1", check.blacklist))
        self.assertIsInstance(r, deprecated.DeprecatedEclass)
        self.assertEqual(r.eclasses, tuple(sorted(check.blacklist.items())))
