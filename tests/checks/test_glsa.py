import os

import pytest
from pkgcheck.checks import SkipCheck, glsa
from pkgcore.ebuild import repo_objs, repository
from pkgcore.test.misc import mk_glsa
from snakeoil.cli import arghparse
from snakeoil.osutils import pjoin

from .. import misc


def mk_pkg(ver, key="dev-util/diffball"):
    return misc.FakePkg(f"{key}-{ver}")


@pytest.fixture
def check(tmp_path):
    glsa_dir = str(tmp_path)
    with open(pjoin(glsa_dir, "glsa-200611-01.xml"), "w") as f:
        f.write(mk_glsa(("dev-util/diffball", ([], [">0.7"]))))
    with open(pjoin(glsa_dir, "glsa-200611-02.xml"), "w") as f:
        f.write(mk_glsa(("dev-util/diffball", ([], ["~>=0.5-r3"]))))
    return glsa.GlsaCheck(arghparse.Namespace(glsa_dir=glsa_dir, gentoo_repo=True))


class TestVulnerabilitiesCheck(misc.ReportTestCase):
    check_kls = glsa.GlsaCheck

    def test_no_glsa_dir(self, tmp_path):
        # TODO: switch to using a repo fixture when available
        repo_dir = str(tmp_path)
        os.makedirs(pjoin(repo_dir, "profiles"))
        os.makedirs(pjoin(repo_dir, "metadata"))
        with open(pjoin(repo_dir, "profiles", "repo_name"), "w") as f:
            f.write("fake\n")
        with open(pjoin(repo_dir, "metadata", "layout.conf"), "w") as f:
            f.write("masters =\n")
        repo_config = repo_objs.RepoConfig(location=repo_dir)
        repo = repository.UnconfiguredTree(repo_config.location, repo_config=repo_config)
        options = arghparse.Namespace(glsa_dir=None, target_repo=repo, gentoo_repo=True)
        with pytest.raises(SkipCheck, match="no available glsa source"):
            glsa.GlsaCheck(options)

    def test_repo_glsa_dir(self, tmp_path):
        # TODO: switch to using a repo fixture when available
        repo_dir = str(tmp_path)
        os.makedirs(pjoin(repo_dir, "profiles"))
        os.makedirs(pjoin(repo_dir, "metadata", "glsa"))
        with open(pjoin(repo_dir, "profiles", "repo_name"), "w") as f:
            f.write("fake\n")
        with open(pjoin(repo_dir, "metadata", "layout.conf"), "w") as f:
            f.write("masters =\n")
        with open(pjoin(repo_dir, "metadata", "glsa", "glsa-202010-01.xml"), "w") as f:
            f.write(mk_glsa(("dev-util/diffball", ([], ["~>=0.5-r3"]))))
        repo_config = repo_objs.RepoConfig(location=repo_dir)
        repo = repository.UnconfiguredTree(repo_config.location, repo_config=repo_config)
        options = arghparse.Namespace(glsa_dir=None, target_repo=repo, gentoo_repo=True)
        check = glsa.GlsaCheck(options)
        assert "dev-util/diffball" in check.vulns

    def test_non_matching(self, check):
        self.assertNoReport(check, mk_pkg("0.5.1"))
        self.assertNoReport(check, mk_pkg("5", "dev-util/diffball2"))

    def test_matching(self, check):
        r = self.assertReport(check, mk_pkg("0.5-r5"))
        assert isinstance(r, glsa.VulnerablePackage)
        assert (r.category, r.package, r.version) == ("dev-util", "diffball", "0.5-r5")
        assert "vulnerable via glsa(200611-02)" in str(r)

        # multiple glsa matches
        self.assertReports(check, mk_pkg("1.0"))
