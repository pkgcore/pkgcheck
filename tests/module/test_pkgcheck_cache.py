import argparse
from functools import partial
from unittest.mock import patch

import pytest
from pkgcheck import __title__ as project
from pkgcheck.scripts import run


class TestPkgcheckCacheParseArgs:

    @pytest.fixture(autouse=True)
    def _setup(self, tool):
        self.tool = tool
        self.args = ['cache']

    def test_argparse_error(self, capsys):
        """Argparse errors are used for error mesages under normal operation."""
        action = argparse.Action(['--foo'], 'foo')
        with patch('pkgcheck.addons.ProfileAddon.check_args') as check_args:
            check_args.side_effect = argparse.ArgumentError(action, 'invalid arg')
            with pytest.raises(SystemExit) as excinfo:
                self.tool.parse_args(self.args)
            assert excinfo.value.code == 2
            out, err = capsys.readouterr()
            err = err.strip().split('\n')
            assert err[-1].startswith('pkgcheck cache: error: argument --foo: invalid arg')

    def test_argparse_error_debug(self, capsys):
        """Argparse errors are raised when parsing args under debug mode."""
        action = argparse.Action(['--foo'], 'foo')
        with patch('pkgcheck.addons.ProfileAddon.check_args') as check_args:
            check_args.side_effect = argparse.ArgumentError(action, 'invalid arg')
            with pytest.raises(argparse.ArgumentError):
                self.tool.parse_args(self.args + ['--debug'])


class TestPkgcheckCache:

    script = partial(run, project)

    @pytest.fixture(autouse=True)
    def _setup(self, fakeconfig, tmp_path):
        self.args = [project, '--config', fakeconfig, 'cache']
        self.cache_dir = str(tmp_path)

    def test_cache_profiles(self, capsys):
        with patch('pkgcheck.const.USER_CACHE_DIR', self.cache_dir):
            # force stubrepo profiles cache regen
            for args in (['-u', '-f'], ['--update', '--force']):
                with patch('sys.argv', self.args + args + ['-t', 'profiles']):
                    with pytest.raises(SystemExit):
                        self.script()

            # verify the profiles cache shows up
            with patch('sys.argv', self.args):
                with pytest.raises(SystemExit) as excinfo:
                    self.script()
                out, err = capsys.readouterr()
                assert not err
                out = out.strip().splitlines()
                assert out[-1] == 'stubrepo'
                assert excinfo.value.code == 0

            # pretend to remove it
            for arg in ('-n', '--dry-run'):
                with patch('sys.argv', self.args + [arg] + ['-rt', 'profiles']):
                    with pytest.raises(SystemExit):
                        self.script()
                    out, err = capsys.readouterr()
                    assert err == ''
                    assert out.startswith(f'Would remove {self.cache_dir}')

            # forcibly remove it
            for arg in ('-r', '--remove'):
                with patch('sys.argv', self.args + [arg] + ['-t', 'profiles']):
                    with pytest.raises(SystemExit):
                        self.script()

            # verify it's gone
            with patch('sys.argv', self.args):
                with pytest.raises(SystemExit) as excinfo:
                    self.script()
                out, err = capsys.readouterr()
                assert (out, err) == ('', '')
                assert excinfo.value.code == 0

    def test_cache_forced_removal(self, capsys):
        with patch('pkgcheck.const.USER_CACHE_DIR', self.cache_dir):
            # force stubrepo profiles cache regen
            with patch('sys.argv', self.args + ['-uf']):
                with pytest.raises(SystemExit):
                    self.script()

            # fail to forcibly remove all
            with patch('pkgcheck.caches.shutil.rmtree') as rmtree, \
                    patch('sys.argv', self.args + ['-rf']):
                rmtree.side_effect = IOError('bad perms')
                with pytest.raises(SystemExit) as excinfo:
                    self.script()
                out, err = capsys.readouterr()
                assert not out
                assert err.strip() == 'pkgcheck cache: error: failed removing cache dir: bad perms'
                assert excinfo.value.code == 2

            # actually forcibly remove all
            with patch('sys.argv', self.args + ['-rf']):
                with pytest.raises(SystemExit) as excinfo:
                    self.script()
                out, err = capsys.readouterr()
                assert (out, err) == ('', '')
                assert excinfo.value.code == 0

            # verify it's gone
            with patch('sys.argv', self.args):
                with pytest.raises(SystemExit) as excinfo:
                    self.script()
                out, err = capsys.readouterr()
                assert (out, err) == ('', '')
                assert excinfo.value.code == 0

            # forcing removal again does nothing
            with patch('sys.argv', self.args + ['-rf']):
                with pytest.raises(SystemExit) as excinfo:
                    self.script()
                out, err = capsys.readouterr()
                assert (out, err) == ('', '')
                assert excinfo.value.code == 0
