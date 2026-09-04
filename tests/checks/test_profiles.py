import os
from os.path import join as pjoin

import pytest

from pkgcheck.checks import profiles as profiles_mod

from .. import misc


class TestRepoProfilesCheck(misc.ReportTestCase):
    check_kls = profiles_mod.RepoProfilesCheck

    @pytest.fixture(autouse=True)
    def _setup(self, tool, repo, tmp_path):
        self.tool = tool
        self.repo = repo
        self.args = ["scan", "--cache-dir", str(tmp_path), "--repo", repo.location]

    def init_check(self):
        options, _ = self.tool.parse_args(self.args)
        check, _required_addons, source = misc.init_check(self.check_kls, options)
        return check, source

    def test_no_unused_dirs(self):
        self.repo.create_profiles([misc.Profile("default", "amd64")])
        self.repo.arches.add("amd64")
        check, source = self.init_check()
        self.assertNoReport(check, source)

    def test_package_use_dir_not_flagged_as_unused(self):
        # package.use (and similarly named files) are allowed by PMS to be
        # either a plain file or a directory of files; a directory-form
        # package.use must not be mistaken for an unused nested profile dir
        self.repo.create_profiles([misc.Profile("default", "amd64")])
        self.repo.arches.add("amd64")
        os.makedirs(pjoin(self.repo.location, "profiles", "default", "package.use"))
        with open(
            pjoin(self.repo.location, "profiles", "default", "package.use", "group"), "w"
        ) as f:
            f.write("cat/pkg foo\n")
        check, source = self.init_check()
        self.assertNoReport(check, source)
