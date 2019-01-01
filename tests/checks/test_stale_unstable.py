import time

from pkgcheck.checks import stale_unstable

from .. import misc


def mk_check(selected_arches=("x86", "ppc", "amd64"), arches=None, verbose=None):
    if arches is None:
        arches = selected_arches

    check = stale_unstable.StaleUnstableReport(
        options=misc.Options(
            selected_arches=selected_arches, stable_arches=arches, verbose=verbose),
        arches=None)
    return check


def mk_pkg(ver, keywords, mtime, slot='0'):
    return misc.FakeTimedPkg(
        f"dev-util/diffball-{ver}",
        mtime, data={"KEYWORDS": keywords, "SLOT": slot})


class TestStaleUnstableReport(misc.ReportTestCase):

    check_kls = stale_unstable.StaleUnstableReport

    @classmethod
    def setup_class(cls):
        cls.now = time.time()
        cls.old = cls.now - (30 * 24 * 3600)

    def test_current_pkg(self):
        self.assertNoReport(mk_check(), [mk_pkg("1.0", "x86", self.now)])

    def test_outdated_stable(self):
        self.assertNoReport(mk_check(), [mk_pkg("1.0", "x86", self.old)])

    def test_outdated_unstable(self):
        self.assertNoReport(mk_check(), [mk_pkg("1.0", "~x86", self.old)])

    def test_outdated_single_stale(self):
        r = self.assertReport(
            mk_check(), [
                mk_pkg("1.0", "amd64 x86", self.old),
                mk_pkg("2.0", "~amd64 x86", self.old),
                ]
            )
        assert isinstance(r, stale_unstable.StaleUnstable)
        assert r.period == 30
        assert r.keywords == ('~amd64',)
        assert 'no change in 30 days' in str(r)

    def test_outdated_multi_stale(self):
        r = self.assertReport(
            mk_check(), [
                mk_pkg("1.0", "amd64 x86", self.old),
                mk_pkg("2.0", "~amd64 ~x86", self.old),
                ]
            )
        assert r.period == 30
        assert r.keywords == ('~amd64', '~x86')

    def test_outdated_multi_pkgs_non_verbose(self):
        reports = self.assertReports(
            mk_check(verbose=False), [
                mk_pkg("1.0", "amd64 x86", self.old),
                mk_pkg("2.0", "~amd64 ~x86", self.old),
                mk_pkg("3.0", "~amd64 ~x86", self.old),
                ]
            )
        assert len(reports) == 1
        for r in reports:
            assert isinstance(r, stale_unstable.StaleUnstable)
            assert r.period == 30
            assert r.keywords == ('~amd64', '~x86')

    def test_outdated_multi_pkgs_verbose(self):
        reports = self.assertReports(
            mk_check(verbose=True), [
                mk_pkg("1.0", "amd64 x86", self.old),
                mk_pkg("2.0", "~amd64 ~x86", self.old),
                mk_pkg("3.0", "~amd64 ~x86", self.old),
                ]
            )
        assert len(reports) == 2
        for r in reports:
            assert isinstance(r, stale_unstable.StaleUnstable)
            assert r.period == 30
            assert r.keywords == ('~amd64', '~x86')

    def test_extraneous_arches(self):
        r = self.assertReport(
            mk_check(), [
                mk_pkg("1.0", "amd64 x86 sparc", self.old),
                mk_pkg("2.0", "~amd64 ~x86 ~sparc", self.old)])
        assert r.keywords == ("~amd64", "~x86")
