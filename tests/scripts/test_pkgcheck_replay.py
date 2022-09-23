import os
import subprocess
import tempfile
from functools import partial
from unittest.mock import patch

import pytest
from pkgcheck import __title__ as project
from pkgcheck.checks.profiles import ProfileWarning
from pkgcheck.reporters import JsonStream
from pkgcheck.scripts import run
from snakeoil.formatters import PlainTextFormatter


class TestPkgcheckReplay:

    script = partial(run, project)

    @pytest.fixture(autouse=True)
    def _setup(self, testconfig):
        self.args = [project, '--config', testconfig, 'replay']

    def test_missing_file_arg(self, capsys):
        with patch('sys.argv', self.args):
            with pytest.raises(SystemExit) as excinfo:
                self.script()
            out, err = capsys.readouterr()
            assert not out
            err = err.strip().split('\n')
            assert len(err) == 1
            assert err[0] == (
                'pkgcheck replay: error: the following arguments are required: FILE')
            assert excinfo.value.code == 2

    def test_replay(self, capsys):
        result = ProfileWarning('profile warning: foo')
        with tempfile.NamedTemporaryFile() as f:
            out = PlainTextFormatter(f)
            with JsonStream(out) as reporter:
                reporter.report(result)
            with patch('sys.argv', self.args + ['-R', 'StrReporter', f.name]):
                with pytest.raises(SystemExit) as excinfo:
                    self.script()
                out, err = capsys.readouterr()
                assert not err
                assert out == 'profile warning: foo\n'
                assert excinfo.value.code == 0

    def test_corrupted_resuts(self, capsys):
        result = ProfileWarning('profile warning: foo')
        with tempfile.NamedTemporaryFile() as f:
            out = PlainTextFormatter(f)
            with JsonStream(out) as reporter:
                reporter.report(result)
            f.write(b'corrupted')
            f.seek(0)
            with patch('sys.argv', self.args + ['-R', 'StrReporter', f.name]):
                with pytest.raises(SystemExit) as excinfo:
                    self.script()
                out, err = capsys.readouterr()
                assert 'corrupted results file' in err
                assert excinfo.value.code == 2

    def test_invalid_file(self, capsys):
        with tempfile.NamedTemporaryFile(mode='wt') as f:
            f.write('invalid file')
            f.seek(0)
            with patch('sys.argv', self.args + ['-R', 'StrReporter', f.name]):
                with pytest.raises(SystemExit) as excinfo:
                    self.script()
                out, err = capsys.readouterr()
                assert err.strip() == 'pkgcheck replay: error: invalid or unsupported replay file'
                assert excinfo.value.code == 2

    def test_replay_pipe_stdin(self):
        script = pytest.REPO_ROOT / 'bin/pkgcheck'
        result = ProfileWarning('profile warning: foo')
        with tempfile.NamedTemporaryFile() as f:
            out = PlainTextFormatter(f)
            with JsonStream(out) as reporter:
                reporter.report(result)
            f.seek(0)
            p = subprocess.run(
                [script, 'replay', '-R', 'StrReporter', '-'],
                stdin=f, stdout=subprocess.PIPE)
            assert p.stdout.decode() == 'profile warning: foo\n'
            assert p.returncode == 0
