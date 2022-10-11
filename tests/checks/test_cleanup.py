from pkgcheck.checks import cleanup
from snakeoil.cli import arghparse

from .. import misc

def mk_pkg(ver, keywords=("x86", "amd64"), slot="0", **kwds):
    return misc.FakePkg(
        f"dev-util/diffball-{ver}",
        data={**kwds, "KEYWORDS": ' '.join(keywords), "SLOT": slot})

class TestRedundantVersion(misc.ReportTestCase):

    check_kls = cleanup.RedundantVersionCheck
    check = check_kls(arghparse.Namespace(stable_only=True), profile_addon={})

    def test_single_version(self):
        self.assertNoReport(self.check, [mk_pkg("0.7.1")])

    def test_live_version(self):
        self.assertNoReport(
            self.check, [mk_pkg('0.7'), mk_pkg('0.9', PROPERTIES='live')])
        self.assertNoReport(
            self.check, [mk_pkg('0.7'), mk_pkg('9999', PROPERTIES='live')])

    def test_no_keywords(self):
        self.assertNoReport(
            self.check, [mk_pkg('0.7'), mk_pkg('0.9', keywords=())])

    def test_disabled_keywords(self):
        self.assertNoReport(
            self.check, [mk_pkg('0.7'), mk_pkg('0.9', keywords=('-x86', '-amd64'))])

    def test_single_redundant(self):
        r = self.assertReport(
            self.check, [mk_pkg(x) for x in ("0.7", "0.8")])
        assert isinstance(r, cleanup.RedundantVersion)
        assert r.later_versions == ("0.8",)
        assert 'slot(0) keywords are overshadowed by version: 0.8' in str(r)

    def test_multiple_redundants(self):
        reports = self.assertReports(
            self.check, [mk_pkg(x) for x in ("0.7", "0.8", "0.9")])
        assert (
            [list(x.later_versions) for x in reports] ==
            [["0.8", "0.9"], ["0.9"]])
        for x in reports:
            assert isinstance(x, cleanup.RedundantVersion)

    def test_multiple_slots(self):
        l = [mk_pkg("0.7", slot="1"), mk_pkg("0.8"),
             mk_pkg("0.9", slot="1")]
        r = self.assertReport(self.check, l)
        assert r.later_versions == ("0.9",)
        assert isinstance(r, cleanup.RedundantVersion)
        assert 'slot(1) keywords are overshadowed by version: 0.9' in str(r)

        l.append(mk_pkg("0.10", keywords=("x86", "amd64", "~sparc")))
        reports = self.assertReports(self.check, l)
        assert ([list(x.later_versions) for x in reports] == [["0.9"], ["0.10"]])

    def test_multiple_keywords(self):
        l = [mk_pkg("0.1", keywords=("~x86", "~amd64")),
             mk_pkg("0.2", keywords=("x86", "~amd64", "~sparc"))]
        r = self.assertReport(self.check, l)
        assert r.later_versions == ("0.2",)


class TestRedundantVersionByStable(misc.ReportTestCase):

    check_kls = cleanup.RedundantVersionCheck
    check = cleanup.RedundantVersionCheck(arghparse.Namespace(stable_only=True), profile_addon={})

    def test_only_unstable(self):
        l = [mk_pkg("0.1", keywords=("~x86", "~amd64")),
             mk_pkg("0.2", keywords=("~x86", "~amd64"))]
        self.assertNoReport(self.check, l)

    def test_only_stable(self):
        l = [mk_pkg("0.1", keywords=("x86", "amd64")),
             mk_pkg("0.2", keywords=("x86", "amd64"))]
        r = self.assertReport(self.check, l)
        assert r.later_versions == ("0.2",)

    def test_mixed_stable(self):
        l = [mk_pkg("0.1", keywords=("x86", "amd64", "~sparc")),
             mk_pkg("0.2", keywords=("x86", "amd64", "~sparc"))]
        r = self.assertReport(self.check, l)
        assert r.later_versions == ("0.2",)

    def test_mixed_history(self):
        l = [mk_pkg("0.1", keywords=("amd64")),
             mk_pkg("0.2", keywords=("~x86", "~amd64")),
             mk_pkg("0.3", keywords=("x86", "amd64")),
             mk_pkg("0.4", keywords=("~x86", "~amd64")),
             mk_pkg("0.5", keywords=("~x86", "~amd64"))]
        r = self.assertReport(self.check, l)
        assert r.later_versions == ("0.3", "0.4", "0.5")

    def test_no_redundant(self):
        l = [mk_pkg("0.1", keywords=("x86", "amd64")),
             mk_pkg("0.2", keywords=("x86", "~amd64"))]
        self.assertNoReport(self.check, l)
