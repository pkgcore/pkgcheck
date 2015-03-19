# Copyright: 2007 Markus Ullmann <jokey@gentoo.org>
# License: BSD/GPL2

import time

from pkgcheck.stale_unstable import StaleUnstableReport
from pkgcheck.test import misc


class TestStaleUnstableReport(misc.ReportTestCase):

    check_kls = StaleUnstableReport

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

        old = now - (30 * 24 * 3600)

        # a current one
        self.assertNoReport(check, mk_pkg("1.0", "x86", now))

        # an outdated, but stable one
        self.assertNoReport(check, mk_pkg("1.0", "x86", old))

        # an outdated, partly unstable one
        self.assertReport(check, mk_pkg("1.0", "~amd64 x86", old))

        # an outdated, fully unstable one
        self.assertReport(check, mk_pkg("1.0", "~amd64 ~x86", old))

        # ensure it reports only specified arches.
        report = self.assertReport(check,
            mk_pkg("1.0", "~amd64 ~x86 ~asdfasdfasdf", old))
        self.assertEqual(report.keywords, tuple(sorted(["~amd64", "~x86"])))
