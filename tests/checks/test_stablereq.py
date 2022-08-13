import os
from datetime import datetime, timedelta

import pytest
from pkgcheck.checks import SkipCheck
from pkgcheck.checks.stablereq import StableRequest, StableRequestCheck
from pkgcore.ebuild.cpv import VersionedCPV
from snakeoil.osutils import pjoin

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
        self.child_git_repo.run(['git', 'pull', 'origin', 'main'])
        self.child_git_repo.run(['git', 'remote', 'set-head', 'origin', 'main'])
        self.child_repo = make_repo(self.child_git_repo.path)

    def init_check(self, options=None, future=0, stable_time=None):
        self.options = options if options is not None else self._options(stable_time=stable_time)
        self.check, required_addons, self.source = init_check(self.check_kls, self.options)
        for k, v in required_addons.items():
            setattr(self, k, v)
        if future:
            self.check.today = datetime.today() + timedelta(days=+future)

    def _options(self, stable_time=None, **kwargs):
        args = [
            'scan', '-q', '--cache-dir', self.cache_dir,
            '--repo', self.child_repo.location,
        ]
        if stable_time is not None:
            args.extend(['--stabletime', str(stable_time)])
        options, _ = self._tool.parse_args(args)
        return options

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
        self.child_git_repo.run(['git', 'pull', 'origin', 'main'])
        self.init_check()
        self.assertNoReport(self.check, self.source)

    def test_uncommitted_local_ebuild(self):
        self.parent_repo.create_ebuild('cat/pkg-1', keywords=['amd64'])
        self.parent_git_repo.add_all('cat/pkg-1')
        self.child_git_repo.run(['git', 'pull', 'origin', 'main'])
        self.child_repo.create_ebuild('cat/pkg-2', keywords=['~amd64'])
        self.init_check(future=30)
        self.assertNoReport(self.check, self.source)

    @pytest.mark.parametrize(("stable_time", "less_days", "more_days"), (
        pytest.param(None,  (0, 1, 10, 20, 29), (30, 31),     id="stable_time=unset"),
        pytest.param(1,     (0,),               (1, 10),      id="stable_time=1"),
        pytest.param(14,    (0, 1, 10, 13),     (14, 15, 30), id="stable_time=14"),
        pytest.param(30,    (0, 1, 10, 20, 29), (30, 31),     id="stable_time=30"),
        pytest.param(100,   (98, 99),           (100, 101),   id="stable_time=100"),
    ))
    def test_existing_stable_keywords(self, stable_time, less_days, more_days):
        self.parent_repo.create_ebuild('cat/pkg-1', keywords=['amd64'])
        self.parent_git_repo.add_all('cat/pkg-1')
        self.parent_repo.create_ebuild('cat/pkg-2', keywords=['~amd64'])
        self.parent_git_repo.add_all('cat/pkg-2')
        self.child_git_repo.run(['git', 'pull', 'origin', 'main'])

        # packages are not old enough to trigger any results
        for future in less_days:
            self.init_check(future=future, stable_time=stable_time)
            self.assertNoReport(self.check, self.source, msg=f"Got report for future={future}")

        # packages are now >= stable_time days old
        for future in more_days:
            self.init_check(future=future, stable_time=stable_time)
            r = self.assertReport(self.check, self.source)
            expected = StableRequest('0', ['~amd64'], future, pkg=VersionedCPV('cat/pkg-2'))
            assert r == expected

    def test_multislot_with_unstable_slot(self):
        self.parent_repo.create_ebuild('cat/pkg-1', keywords=['amd64'])
        self.parent_git_repo.add_all('cat/pkg-1')
        self.parent_repo.create_ebuild('cat/pkg-2', keywords=['~amd64'], slot='1')
        self.parent_git_repo.add_all('cat/pkg-2')
        self.child_git_repo.run(['git', 'pull', 'origin', 'main'])
        self.init_check(future=30)
        r = self.assertReport(self.check, self.source)
        expected = StableRequest('1', ['~amd64'], 30, pkg=VersionedCPV('cat/pkg-2'))
        assert r == expected

    def test_moved_category(self):
        self.parent_repo.create_ebuild('cat/pkg-1', keywords=['amd64'])
        self.parent_git_repo.add_all('cat/pkg-1')
        self.parent_repo.create_ebuild('cat/pkg-2', keywords=['~amd64'])
        self.parent_git_repo.add_all('cat/pkg-2')
        self.parent_git_repo.move('cat', 'newcat')
        self.child_git_repo.run(['git', 'pull', 'origin', 'main'])
        self.init_check(future=30)
        r = self.assertReport(self.check, self.source)
        expected = StableRequest('0', ['~amd64'], 30, pkg=VersionedCPV('newcat/pkg-2'))
        assert r == expected

    def test_moved_package(self):
        self.parent_repo.create_ebuild('cat/pkg-1', keywords=['amd64'])
        self.parent_git_repo.add_all('cat/pkg-1')
        self.parent_repo.create_ebuild('cat/pkg-2', keywords=['~amd64'])
        self.parent_git_repo.add_all('cat/pkg-2')

        # rename pkg and commit results
        path = self.parent_git_repo.path
        new_pkg_dir = pjoin(path, 'cat/newpkg')
        os.rename(pjoin(path, 'cat/pkg'), new_pkg_dir)
        for i, f in enumerate(sorted(os.listdir(new_pkg_dir))):
            os.rename(pjoin(new_pkg_dir, f), pjoin(new_pkg_dir, f'newpkg-{i}.ebuild'))
        self.parent_git_repo.add_all()
        self.child_git_repo.run(['git', 'pull', 'origin', 'main'])

        self.init_check(future=30)
        r = self.assertReport(self.check, self.source)
        expected = StableRequest('0', ['~amd64'], 30, pkg=VersionedCPV('cat/newpkg-2'))
        assert r == expected

    def test_renamed_ebuild(self):
        self.parent_repo.create_ebuild('cat/pkg-1', keywords=['amd64'])
        self.parent_git_repo.add_all('cat/pkg-1')
        self.parent_repo.create_ebuild('cat/pkg-2_rc1', keywords=['~amd64'])
        self.parent_git_repo.add_all('cat/pkg-2_rc1')
        self.parent_git_repo.move('cat/pkg/pkg-2_rc1.ebuild', 'cat/pkg/pkg-2.ebuild')
        self.child_git_repo.run(['git', 'pull', 'origin', 'main'])
        self.init_check(future=30)
        r = self.assertReport(self.check, self.source)
        expected = StableRequest('0', ['~amd64'], 30, pkg=VersionedCPV('cat/pkg-2'))
        assert r == expected

    def test_modified_ebuild(self):
        self.parent_repo.create_ebuild('cat/pkg-1', keywords=['amd64'])
        self.parent_git_repo.add_all('cat/pkg-1')
        self.parent_repo.create_ebuild('cat/pkg-2', keywords=['~amd64'])
        self.parent_git_repo.add_all('cat/pkg-2')
        with open(pjoin(self.parent_git_repo.path, 'cat/pkg/pkg-2.ebuild'), 'a') as f:
            f.write('# comment\n')
        self.parent_git_repo.add_all('cat/pkg-2: add comment')
        self.child_git_repo.run(['git', 'pull', 'origin', 'main'])
        self.init_check(future=30)
        r = self.assertReport(self.check, self.source)
        expected = StableRequest('0', ['~amd64'], 30, pkg=VersionedCPV('cat/pkg-2'))
        assert r == expected
