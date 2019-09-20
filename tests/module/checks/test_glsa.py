from pkgcore.test.misc import mk_glsa
import pytest
from snakeoil.osutils import pjoin

from pkgcheck.checks import glsa

from .. import misc


def mk_pkg(ver, key="dev-util/diffball"):
    return misc.FakePkg(f"{key}-{ver}")


@pytest.fixture
def check(tmpdir):
    with open(pjoin(str(tmpdir), "glsa-200611-01.xml"), "w") as f:
        f.write(mk_glsa(("dev-util/diffball", ([], [">0.7"]))))
    with open(pjoin(str(tmpdir), "glsa-200611-02.xml"), "w") as f:
        f.write(mk_glsa(("dev-util/diffball", ([], ["~>=0.5-r3"]))))
    return glsa.GlsaCheck(
        misc.Options(glsa_location=str(tmpdir), glsa_enabled=True))


class TestVulnerabilitiesCheck(misc.ReportTestCase):

    check_kls = glsa.GlsaCheck

    def test_non_matching(self, check):
        self.assertNoReport(check, mk_pkg("0.5.1"))
        self.assertNoReport(check, mk_pkg("5", "dev-util/diffball2"))

    def test_matching(self, check):
        r = self.assertReport(check, mk_pkg("0.5-r5"))
        assert isinstance(r, glsa.VulnerablePackage)
        assert (
            (r.category, r.package, r.version) ==
            ("dev-util", "diffball", "0.5-r5"))
        assert 'vulnerable via glsa(200611-02)' in str(r)

        # multiple glsa matches
        self.assertReports(check, mk_pkg("1.0"))
