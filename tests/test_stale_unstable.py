import time

from pkgcheck.stale_unstable import StaleUnstableReport
from pkgcheck.test import misc


class TestStaleUnstableReport(misc.ReportTestCase):

    check_kls = StaleUnstableReport

    def mk_pkg(self, ver, keywords, mtime, slot='0'):
        return misc.FakeTimedPkg(
            f"dev-util/diffball-{ver}",
            mtime, data={"KEYWORDS": keywords, "SLOT": slot})

    def test_it(self):
        now = time.time()
        check = StaleUnstableReport(
            options=misc.Options(
                selected_arches=("x86", "ppc", "amd64"),
                arches=("x86", "ppc", "amd64"),
                verbose=None),
            arches=None)

        check.start()

        old = now - (30 * 24 * 3600)

        # a current one
        self.assertNoReport(check, [self.mk_pkg("1.0", "x86", now)])

        # an outdated, but stable one
        self.assertNoReport(check, [self.mk_pkg("1.0", "x86", old)])

        # an outdated, but unstable one
        self.assertNoReport(check, [self.mk_pkg("1.0", "~x86", old)])

        # an outdated, partly unstable one
        r = self.assertReport(
            check, [
                self.mk_pkg("1.0", "amd64 x86", old),
                self.mk_pkg("2.0", "~amd64 x86", old),
                ]
            )
        assert r.period == 30
        assert r.keywords == ('~amd64',)
        assert 'no change in 30 days' in str(r)

        # an outdated, fully unstable one
        r = self.assertReport(
            check, [
                self.mk_pkg("1.0", "amd64 x86", old),
                self.mk_pkg("2.0", "~amd64 ~x86", old),
                ]
            )
        assert r.period == 30
        assert r.keywords == ('~amd64', '~x86')

        # ensure it reports only specified arches.
        r = self.assertReport(
            check, [
                self.mk_pkg("1.0", "amd64 x86 sparc", old),
                self.mk_pkg("2.0", "~amd64 ~x86 ~sparc", old)])
        assert r.keywords == ("~amd64", "~x86")
