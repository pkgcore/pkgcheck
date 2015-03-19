# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: BSD/GPL2

from pkgcheck.test import misc
from pkgcheck.deprecated import DeprecatedEclassReport as dep_eclass


class TestDeprecatedEclass(misc.ReportTestCase):

    check_kls = dep_eclass

    def mk_pkg(self, ver, eclasses):
        return misc.FakePkg(
            "dev-util/diffball-%s" % ver,
            data={"_eclasses_": {}.fromkeys(eclasses)})

    def test_it(self):
        # single version, shouldn't yield.
        check = dep_eclass(None, None)
        self.assertNoReport(check, self.mk_pkg("0.7.1", []))
        reports = self.assertReports(
            check, self.mk_pkg("0.1", check.blacklist))
        self.assertEqual(len(reports), 1)
