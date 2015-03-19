# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: BSD/GPL2

from pkgcore.test.pkgsets.test_glsa import mk_glsa
from snakeoil.osutils import pjoin
from snakeoil.test.mixins import TempDirMixin

from pkgcheck.glsa_scan import TreeVulnerabilitiesReport as vuln_report
from pkgcheck.test import misc


class TestVulnerabilitiesReport(TempDirMixin, misc.ReportTestCase):

    check_kls = vuln_report

    def mk_pkg(self, ver, key="dev-util/diffball"):
        return misc.FakePkg("%s-%s" % (key, ver))

    def test_it(self):
        # single version, shouldn't yield.
        check = vuln_report(
            misc.Options(glsa_location=self.dir, glsa_enabled=True))
        with open(pjoin(self.dir, "glsa-200611-01.xml"), "w") as f:
            f.write(mk_glsa(("dev-util/diffball", ([], [">0.7"]))))
        with open(pjoin(self.dir, "glsa-200611-02.xml"), "w") as f:
            f.write(mk_glsa(("dev-util/diffball", ([], ["~>=0.5-r3"]))))
        check.start()
        self.assertNoReport(check, self.mk_pkg("0.5.1"))
        r = self.assertReports(check, self.mk_pkg("0.5-r5"))
        self.assertEqual(len(r), 1)
        self.assertEqual(
            (r[0].category, r[0].package, r[0].version),
            ("dev-util", "diffball", "0.5-r5"))
        self.assertReports(check, self.mk_pkg("1.0"))
        self.assertNoReport(check, self.mk_pkg("5", "dev-util/diffball2"))
