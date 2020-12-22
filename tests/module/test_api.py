import pytest
from pkgcheck import PkgcheckException, scan


class TestScanApi:

    @pytest.fixture(autouse=True)
    def _setup(self, testconfig):
        self.base_args = ['--config', testconfig]
        self.scan_args = ['--config', 'no', '--cache', 'no']

    def test_argparse_error(self, repo):
        with pytest.raises(PkgcheckException, match='unrecognized arguments'):
            scan(['-r', repo.location, '--foo'])

    def test_no_scan_args(self):
        pipe = scan(base_args=self.base_args)
        assert pipe.options.target_repo.repo_id == 'standalone'

    def test_no_base_args(self, repo):
        assert [] == list(scan(self.scan_args + ['-r', repo.location]))
