# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: BSD/GPL2

from pkgcheck.test import misc
from pkgcheck.imlate import ImlateReport


class TestImlateReport(misc.ReportTestCase):

    check_kls = ImlateReport

    def mk_pkg(self, ver, keywords=""):
        return misc.FakePkg(
            "dev-util/diffball-%s" % ver, data={"KEYWORDS": keywords})

    def test_it(self):
        mk_pkg = self.mk_pkg
        check = ImlateReport(misc.Options(
            arches=("x86", "ppc", "amd64"),
            reference_arches=("x86", "ppc", "amd64"),
            target_arches=("x86", "ppc")), None)

        self.assertNoReport(
            check,
            [mk_pkg(str(x), "~x86 ~amd64") for x in xrange(10)])

        # assert single 0.9/0.8
        report = self.assertReports(
            check,
            [mk_pkg("0.8", "~x86"), mk_pkg("0.9", "~x86 amd64")])
        self.assertEqual(len(report), 1)
        self.assertEqual(report[0].stable, ("amd64",))
        self.assertEqual(report[0].version, "0.9")

        # insert a 0.7 in; it should not show.
        # additionally, insert an arch we don't care about...

        report = self.assertReports(
            check,
            [mk_pkg("0.7", "~x86"),
             mk_pkg("0.8", "~x86 ~foo"), mk_pkg("0.9", "~x86 amd64"),
             mk_pkg("0.10", "foo")])
        self.assertEqual(len(report), 1)
        self.assertEqual(report[0].stable, ("amd64",))
        self.assertEqual(report[0].version, "0.9")
