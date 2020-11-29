import pytest
from datetime import datetime, timedelta
from pkgcore.ebuild.cpv import VersionedCPV
from pkgcheck.checks import SkipCheck
from pkgcheck.checks.stablereq import StableRequest, StableRequestCheck

from ..misc import ReportTestCase, init_check


class TestStableRequestCheck(ReportTestCase):

    check_kls = StableRequestCheck

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, tool, make_repo, make_git_repo):
        self._tool = tool
        self.cache_dir = str(tmp_path)

        # initialize parent repo
        self.parent_git_repo = make_git_repo()
        self.parent_repo = make_repo(self.parent_git_repo.path, repo_id='gentoo')
        self.parent_git_repo.add_all('initial commit')
        # create a stub pkg and commit it
        self.parent_repo.create_ebuild('cat/pkg-0')
        self.parent_git_repo.add_all('cat/pkg-0')

        # initialize child repo
        self.child_git_repo = make_git_repo()
        self.child_git_repo.run(['git', 'remote', 'add', 'origin', self.parent_git_repo.path])
        self.child_git_repo.run(['git', 'pull', 'origin', 'master'])
        self.child_git_repo.run(['git', 'remote', 'set-head', 'origin', 'master'])
        self.child_repo = make_repo(self.child_git_repo.path)

    def init_check(self, options=None, future=True):
        self.options = options if options is not None else self._options()
        self.check, required_addons, self.source = init_check(self.check_kls, self.options)
        for k, v in required_addons.items():
            setattr(self, k, v)
        self.cache_file = self.git_addon.cache_file(self.child_repo)
        if future:
            self.check.today = datetime.today() + timedelta(days=+30)

    def _options(self, **kwargs):
        args = ['scan', '--cache-dir', self.cache_dir, '--repo', self.child_repo.location]
        options, _ = self._tool.parse_args(args)
        return options

    def test_no_gentoo_repo(self):
        options = self._options()
        options.gentoo_repo = False
        with pytest.raises(SkipCheck, match='not running against gentoo repo'):
            self.init_check(options)

    def test_no_git_support(self):
        options = self._options()
        options.cache['git'] = False
        with pytest.raises(SkipCheck, match='git cache support required'):
            self.init_check(options)

    def test_no_stable_keywords(self):
        self.parent_repo.create_ebuild('cat/pkg-1', keywords=['~amd64'])
        self.parent_git_repo.add_all('cat/pkg-1')
        self.parent_repo.create_ebuild('cat/pkg-2', keywords=['~amd64'])
        self.parent_git_repo.add_all('cat/pkg-2')
        self.child_git_repo.run(['git', 'pull', 'origin', 'master'])
        self.init_check()
        self.assertNoReport(self.check, self.source)

    def test_existing_stable_keywords(self):
        self.parent_repo.create_ebuild('cat/pkg-1', keywords=['amd64'])
        self.parent_git_repo.add_all('cat/pkg-1')
        self.parent_repo.create_ebuild('cat/pkg-2', keywords=['~amd64'])
        self.parent_git_repo.add_all('cat/pkg-2')
        self.child_git_repo.run(['git', 'pull', 'origin', 'master'])
        self.init_check()
        r = self.assertReport(self.check, self.source)
        expected = StableRequest('0', ['~amd64'], 30, pkg=VersionedCPV('cat/pkg-2'))
        assert r == expected
