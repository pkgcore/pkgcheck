import os
from functools import partial
from unittest.mock import patch

import pytest
from pkgcheck import __title__ as project
from pkgcheck.scripts import run


class TestPkgcheckCache:

    script = partial(run, project)

    @pytest.fixture(autouse=True)
    def _setup(self, testconfig, tmp_path):
        self.cache_dir = str(tmp_path)
        self.args = [
            project, '--config', testconfig,
            'cache', '--cache-dir', self.cache_dir]

    def test_cache_profiles(self, capsys):
        # force standalone repo profiles cache regen
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
            assert out[-1].startswith('standalone-')
            assert excinfo.value.code == 0

        # pretend to remove it
        for arg in ('-n', '--dry-run'):
            with patch('sys.argv', self.args + [arg] + ['-Rt', 'profiles']):
                with pytest.raises(SystemExit):
                    self.script()
                out, err = capsys.readouterr()
                assert err == ''
                assert out.startswith(f'Would remove {self.cache_dir}')

        # fail to remove it
        for arg in ('-R', '--remove'):
            with patch('pkgcheck.addons.caches.os.unlink') as unlink, \
                    patch('sys.argv', self.args + [arg] + ['-t', 'profiles']):
                unlink.side_effect = IOError('bad perms')
                with pytest.raises(SystemExit) as excinfo:
                    self.script()
                out, err = capsys.readouterr()
                assert not out
                assert os.listdir(self.cache_dir)
                assert err.startswith('pkgcheck cache: error: failed removing profiles cache')
                assert excinfo.value.code == 2

        # actually remove it
        for arg in ('-R', '--remove'):
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
        # force standalone repo profiles cache regen
        with patch('sys.argv', self.args + ['-uf']):
            with pytest.raises(SystemExit):
                self.script()

        # fail to forcibly remove all
        with patch('pkgcheck.addons.caches.shutil.rmtree') as rmtree, \
                patch('sys.argv', self.args + ['-Rf']):
            rmtree.side_effect = IOError('bad perms')
            with pytest.raises(SystemExit) as excinfo:
                self.script()
            out, err = capsys.readouterr()
            assert not out
            assert err.strip() == 'pkgcheck cache: error: failed removing cache dir: bad perms'
            assert excinfo.value.code == 2

        # actually forcibly remove all
        with patch('sys.argv', self.args + ['-Rf']):
            with pytest.raises(SystemExit) as excinfo:
                self.script()
            out, err = capsys.readouterr()
            assert (out, err) == ('', '')
            assert excinfo.value.code == 0

        # cache dir has been entirely blown away
        assert not os.path.exists(self.cache_dir)

        # forcing removal again does nothing
        with patch('sys.argv', self.args + ['-Rf']):
            with pytest.raises(SystemExit) as excinfo:
                self.script()
            out, err = capsys.readouterr()
            assert (out, err) == ('', '')
            assert excinfo.value.code == 0
