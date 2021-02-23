from functools import partial
from unittest.mock import patch

import pytest
from pkgcheck.checks.metadata import InvalidSlot
from pkgcheck.reporters import JsonStream
from pkgcheck.scripts import run
from pkgcore.ebuild.cpv import VersionedCPV


class TestPkgcheckCi:

    script = partial(run, 'pkgcheck')

    @pytest.fixture(autouse=True)
    def _setup(self, testconfig, tmp_path):
        self.cache_dir = str(tmp_path)
        base_args = ['--config', testconfig]
        self.scan_args = ['--config', 'no', '--cache-dir', self.cache_dir]
        # args for running pkgcheck like a script
        self.args = ['pkgcheck'] + base_args + ['ci'] + self.scan_args

    def test_empty_repo(self, capsys, repo):
        with patch('sys.argv', self.args + [repo.location]):
            with pytest.raises(SystemExit) as excinfo:
                self.script()
            assert excinfo.value.code == 0
            out, err = capsys.readouterr()
            assert out == err == ''

    def test_exit_status(self, repo):
        # create good ebuild and another with an invalid EAPI
        repo.create_ebuild('cat/pkg-0')
        repo.create_ebuild('cat/pkg-1', eapi='-1')
        # exit status isn't enabled by default
        args = ['-r', repo.location]
        with patch('sys.argv', self.args + args):
            with pytest.raises(SystemExit) as excinfo:
                self.script()
            assert excinfo.value.code == 0

        # all error level results are flagged by default when enabled
        with patch('sys.argv', self.args + args + ['--exit']):
            with pytest.raises(SystemExit) as excinfo:
                self.script()
            assert excinfo.value.code == 1

        # selective error results will only flag those specified
        with patch('sys.argv', self.args + args + ['--exit', 'InvalidSlot']):
            with pytest.raises(SystemExit) as excinfo:
                self.script()
            assert excinfo.value.code == 0
        with patch('sys.argv', self.args + args + ['--exit', 'InvalidEapi']):
            with pytest.raises(SystemExit) as excinfo:
                self.script()
            assert excinfo.value.code == 1

    def test_failures(self, tmp_path, repo):
        repo.create_ebuild('cat/pkg-1', slot='')
        failures = str(tmp_path / 'failures.json')
        args = ['--failures', failures, '--exit', '-r', repo.location]
        with patch('sys.argv', self.args + args):
            with pytest.raises(SystemExit) as excinfo:
                self.script()
            assert excinfo.value.code == 1

        with open(str(failures)) as f:
            results = list(JsonStream.from_iter(f))
            pkg = VersionedCPV('cat/pkg-1')
            assert results == [InvalidSlot('slot', 'SLOT cannot be unset or empty', pkg=pkg)]
