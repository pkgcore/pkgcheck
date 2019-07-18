from pkgcheck.checks import imlate

from .. import misc


def mk_check(selected_arches=("x86", "ppc", "amd64"), arches=None,
             stable_arches=None, source_arches=None):
    if arches is None:
        arches = selected_arches
    if stable_arches is None:
        stable_arches = selected_arches
    return imlate.ImlateReport(
        misc.Options(selected_arches=selected_arches, arches=arches,
                     stable_arches=stable_arches, source_arches=source_arches))


def mk_pkg(ver, keywords=""):
    return misc.FakePkg(f"dev-util/diffball-{ver}", data={"SLOT": "0", "KEYWORDS": keywords})


class TestImlateReport(misc.ReportTestCase):

    check_kls = imlate.ImlateReport

    def test_all_unstable(self):
        self.assertNoReport(
            mk_check(),
            [mk_pkg(str(x), "~x86 ~amd64") for x in range(10)])

    def test_all_stable(self):
        r = self.assertNoReport(
            mk_check(),
            [mk_pkg("0.9", "amd64 x86")])

    def test_unselected_arch(self):
        r = self.assertNoReport(
            mk_check(),
            [mk_pkg("0.9", "~mips amd64")])

    def test_specified_stable_arches(self):
        # pkg doesn't have any unstable arches we care about
        r = self.assertNoReport(
            mk_check(source_arches=('arm', 'arm64')),
            [mk_pkg("0.9", "~x86 amd64")])

        # pkg doesn't have any stable arches we care about
        r = self.assertNoReport(
            mk_check(source_arches=('arm64',)),
            [mk_pkg("0.9", "~x86 amd64")])

        # only flag arches we care about
        r = self.assertReport(
            mk_check(source_arches=('amd64',), selected_arches=('arm64',)),
            [mk_pkg("0.9", "~arm64 ~x86 amd64")])
        assert isinstance(r, imlate.PotentialStable)
        assert r.stable == ("amd64",)
        assert r.keywords == ("~arm64",)
        assert r.version == "0.9"

    def test_lagging_keyword(self):
        r = self.assertReport(
            mk_check(),
            [mk_pkg("0.8", "x86 amd64"),
             mk_pkg("0.9", "x86 ~amd64")])
        assert isinstance(r, imlate.LaggingStable)
        assert r.stable == ("x86",)
        assert r.keywords == ("~amd64",)
        assert r.version == "0.9"
        assert 'x86' in str(r) and '~amd64' in str(r)

    def test_potential_keyword(self):
        r = self.assertReport(
            mk_check(),
            [mk_pkg("0.9", "~x86 amd64")])
        assert isinstance(r, imlate.PotentialStable)
        assert r.stable == ("amd64",)
        assert r.keywords == ("~x86",)
        assert r.version == "0.9"
        assert 'amd64' in str(r) and '~x86' in str(r)

    def test_multiple_unstable_pkgs(self):
        r = self.assertReport(
            mk_check(),
            [mk_pkg("0.7", "~x86"),
             mk_pkg("0.8", "~x86"),
             mk_pkg("0.9", "~x86 amd64")])
        assert r.stable == ("amd64",)
        assert r.keywords == ("~x86",)
        assert r.version == "0.9"

    def test_multiple_stable_arches(self):
        r = self.assertReport(
            mk_check(),
            [mk_pkg("0.7", "~x86 ~ppc"),
             mk_pkg("0.9", "~x86 ppc amd64")])
        assert r.stable == ("amd64", "ppc")
        assert r.keywords == ("~x86",)
        assert r.version == "0.9"

    def test_multiple_potential_arches(self):
        r = self.assertReport(
            mk_check(),
            [mk_pkg("0.7", "~x86"),
             mk_pkg("0.9", "~x86 ~ppc amd64")])
        assert r.stable == ("amd64",)
        assert r.keywords == ("~ppc", "~x86",)
        assert r.version == "0.9"

    def test_drop_newer_slot_stables(self):
        selected_arches=("x86", "amd64")
        all_arches=("x86", "amd64", "arm64")
        r = self.assertReport(
            mk_check(selected_arches=selected_arches, arches=all_arches),
            [mk_pkg("0.7", "amd64 x86 ~arm64"),
             mk_pkg("0.8", "amd64 ~x86 ~arm64"),
             mk_pkg("0.9", "~amd64 ~x86 arm64")]
        )
        assert isinstance(r, imlate.LaggingStable)
        assert r.stable == ('amd64',)
        assert r.keywords == ('~x86',)
        assert r.version == '0.8'
