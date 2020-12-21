import pytest
from pkgcheck import PkgcheckException, scan
from pkgcore import const as pkgcore_const
from pkgcore.config import load_config
from snakeoil.osutils import pjoin


class TestScanApi:

    @pytest.fixture(autouse=True)
    def _setup(self, testconfig):
        self.base_args = ['--config', testconfig]
        self.scan_args = ['--config', 'no', '--cache', 'no']

    def test_empty_repo(self, repo):
        args = self.scan_args + ['-r', repo.location]
        assert [] == list(scan(args, base_args=self.base_args))

    def test_argparse_error(self, repo):
        with pytest.raises(PkgcheckException, match='unrecognized arguments'):
            scan(['-r', repo.location, '--foo'])

    def test_no_scan_args(self):
        pipe = scan(base_args=self.base_args)
        assert pipe.options.target_repo.repo_id == 'standalone'

    def test_no_args(self):
        config = load_config()
        repo = config.get_default('repo')

        # non-Gentoo system
        if repo is None or repo.location == pjoin(pkgcore_const.DATA_PATH, 'stubrepo'):
            with pytest.raises(PkgcheckException, match='no default repo found'):
                scan()
        else:
            pipe = scan()
            assert pipe.options.target_repo.repo_id
