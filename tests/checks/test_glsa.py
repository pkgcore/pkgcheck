from pkgcore.test.misc import mk_glsa
import pytest
from snakeoil.osutils import pjoin

from pkgcheck.checks.glsa import TreeVulnerabilitiesReport as vuln_report

from .. import misc


def mk_pkg(ver, key="dev-util/diffball"):
    return misc.FakePkg(f"{key}-{ver}")


@pytest.fixture
def check(tmpdir):
    check = vuln_report(
        misc.Options(glsa_location=str(tmpdir), glsa_enabled=True))

    with open(pjoin(str(tmpdir), "glsa-200611-01.xml"), "w") as f:
        f.write(mk_glsa(("dev-util/diffball", ([], [">0.7"]))))
    with open(pjoin(str(tmpdir), "glsa-200611-02.xml"), "w") as f:
        f.write(mk_glsa(("dev-util/diffball", ([], ["~>=0.5-r3"]))))
    return check


class TestVulnerabilitiesReport(misc.ReportTestCase):

    check_kls = vuln_report

    def test_non_matching(self, check):
        self.assertNoReport(check, mk_pkg("0.5.1"))

    def test_matching(self, check):
        r = self.assertReports(check, mk_pkg("0.5-r5"))
        assert len(r) == 1
        assert (
            (r[0].category, r[0].package, r[0].version) ==
            ("dev-util", "diffball", "0.5-r5"))
        self.assertReports(check, mk_pkg("1.0"))
        self.assertNoReport(check, mk_pkg("5", "dev-util/diffball2"))
