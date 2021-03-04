import itertools
from functools import partial
from unittest.mock import patch

import pytest
from pkgcheck import __title__ as project
from pkgcheck import base, objects
from pkgcheck.addons import caches
from pkgcheck.scripts import run


class TestPkgcheckShow:

    script = partial(run, project)

    @pytest.fixture(autouse=True)
    def _setup(self, testconfig):
        self.args = [project, '--config', testconfig, 'show']

    def test_show_no_args(self, capsys):
        # defaults to outputting keywords list if no option is passed
        with patch('sys.argv', self.args):
            with pytest.raises(SystemExit) as excinfo:
                self.script()
            out, err = capsys.readouterr()
            assert not err
            out = out.strip().split('\n')
            assert out == sorted(objects.KEYWORDS.keys())
            assert excinfo.value.code == 0

    def test_show_keywords(self, capsys):
        for arg in ('-k', '--keywords'):
            # regular mode
            with patch('sys.argv', self.args + [arg]):
                with pytest.raises(SystemExit) as excinfo:
                    self.script()
                out, err = capsys.readouterr()
                assert not err
                out = out.strip().split('\n')
                regular_output = out
                assert out == sorted(objects.KEYWORDS.keys())
                assert excinfo.value.code == 0

            # verbose mode
            with patch('sys.argv', self.args + [arg, '-v']):
                with pytest.raises(SystemExit) as excinfo:
                    self.script()
                out, err = capsys.readouterr()
                assert not err
                out = out.strip().split('\n')
                verbose_output = out
                assert excinfo.value.code == 0

            # verbose output shows much more info
            assert len(regular_output) < len(verbose_output)

    def test_show_checks(self, capsys):
        for arg in ('-c', '--checks'):
            # regular mode
            with patch('sys.argv', self.args + [arg]):
                with pytest.raises(SystemExit) as excinfo:
                    self.script()
                out, err = capsys.readouterr()
                assert not err
                out = out.strip().split('\n')
                regular_output = out
                assert out == sorted(objects.CHECKS.keys())
                assert excinfo.value.code == 0

            # verbose mode
            with patch('sys.argv', self.args + [arg, '-v']):
                with pytest.raises(SystemExit) as excinfo:
                    self.script()
                out, err = capsys.readouterr()
                assert not err
                out = out.strip().split('\n')
                verbose_output = out
                assert excinfo.value.code == 0

            # verbose output shows much more info
            assert len(regular_output) < len(verbose_output)

    def test_show_scopes(self, capsys):
        for arg in ('-s', '--scopes'):
            with patch('sys.argv', self.args + [arg]):
                with pytest.raises(SystemExit) as excinfo:
                    self.script()
                out, err = capsys.readouterr()
                assert not err
                out = out.strip().split('\n')
                assert out == list(base.scopes)
                assert excinfo.value.code == 0
                regular_output = '\n'.join(itertools.chain(out))

            # verbose mode
            with patch('sys.argv', self.args + [arg, '-v']):
                with pytest.raises(SystemExit) as excinfo:
                    self.script()
                out, err = capsys.readouterr()
                assert not err
                out = out.strip().split('\n')
                assert excinfo.value.code == 0
                verbose_output = '\n'.join(itertools.chain(out))

            # verbose output shows more info
            assert len(regular_output) < len(verbose_output)

    def test_show_reporters(self, capsys):
        for arg in ('-r', '--reporters'):
            # regular mode
            with patch('sys.argv', self.args + [arg]):
                with pytest.raises(SystemExit) as excinfo:
                    self.script()
                out, err = capsys.readouterr()
                assert not err
                out = out.strip().split('\n')
                regular_output = out
                assert out == sorted(objects.REPORTERS.keys())
                assert excinfo.value.code == 0

            # verbose mode
            with patch('sys.argv', self.args + [arg, '-v']):
                with pytest.raises(SystemExit) as excinfo:
                    self.script()
                out, err = capsys.readouterr()
                assert not err
                out = out.strip().split('\n')
                verbose_output = out
                assert excinfo.value.code == 0

            # verbose output shows much more info
            assert len(regular_output) < len(verbose_output)

    def test_show_caches(self, capsys):
        for arg in ('-C', '--caches'):
            with patch('sys.argv', self.args + [arg]):
                with pytest.raises(SystemExit) as excinfo:
                    self.script()
                out, err = capsys.readouterr()
                assert not err
                out = out.strip().split('\n')
                cache_objs = caches.CachedAddon.caches.values()
                assert out == sorted(x.type for x in cache_objs)
                assert excinfo.value.code == 0
                regular_output = '\n'.join(itertools.chain(out))

            # verbose mode
            with patch('sys.argv', self.args + [arg, '-v']):
                with pytest.raises(SystemExit) as excinfo:
                    self.script()
                out, err = capsys.readouterr()
                assert not err
                out = out.strip().split('\n')
                assert excinfo.value.code == 0
                verbose_output = '\n'.join(itertools.chain(out))

            # verbose output shows more info
            assert len(regular_output) < len(verbose_output)
