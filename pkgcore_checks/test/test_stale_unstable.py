# Copyright: 2007 Markus Ullmann <jokey@gentoo.org>
# License: GPL2

from pkgcore_checks.test import misc
from pkgcore_checks.stale_unstable import StaleUnstableReport
import time


class TestStaleUnstableReport(misc.ReportTestCase):

    def mk_pkg(self, ver, keywords ,mtime):
        return misc.FakeTimedPkg("dev-util/diffball-%s" % ver,
            mtime,data={"KEYWORDS":keywords})

    def test_it(self):
        now = time.time()
        mk_pkg = self.mk_pkg
        check  = StaleUnstableReport(misc.Options(arches=("x86", "ppc", "amd64"),
            reference_arches=("x86", "ppc", "amd64"),
            target_arches=("x86", "ppc")),  None)
	
        check.start()
        
        # a current one
        self.assertNoReport(check, mk_pkg("1.0", "x86",now))

        # an outdated, but stable one
        self.assertNoReport(check, mk_pkg("1.0", "x86",(now-30*24*3600-1)))

        # an outdated, partly unstable one
        report = self.assertReports(check, mk_pkg("1.0", "~amd64 x86",(now-30*24*3600-1)))
        self.assertEqual(len(report), 1)

        # an outdated, fully unstable one
        report = self.assertReports(check, mk_pkg("1.0", "~amd64 ~x86",(now-30*24*3600-1)))
        self.assertEqual(len(report), 1)
