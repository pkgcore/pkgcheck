from functools import partial
from unittest.mock import patch

from pkgcore import const
from pytest import raises
from snakeoil.osutils import pjoin

from pkgcheck import base, plugins, __title__ as project
from pkgcore.plugin import get_plugins
from pkgcheck.scripts import run, pkgcheck


def test_script_run(capsys):
    """Test regular code path for running scripts."""
    script = partial(run, project)

    with patch(f'{project}.scripts.import_module') as import_module:
        import_module.side_effect = ImportError("baz module doesn't exist")

        # default error path when script import fails
        with patch('sys.argv', [project]):
            with raises(SystemExit) as excinfo:
                script()
            assert excinfo.value.code == 1
            out, err = capsys.readouterr()
            err = err.strip().split('\n')
            assert len(err) == 3
            assert err[0] == "Failed importing: baz module doesn't exist!"
            assert err[1].startswith(f"Verify that {project} and its deps")
            assert err[2] == "Add --debug to the commandline for a traceback."

        # running with --debug should raise an ImportError when there are issues
        with patch('sys.argv', [project, '--debug']):
            with raises(ImportError):
                script()
            out, err = capsys.readouterr()
            err = err.strip().split('\n')
            assert len(err) == 2
            assert err[0] == "Failed importing: baz module doesn't exist!"
            assert err[1].startswith(f"Verify that {project} and its deps")

        import_module.reset_mock()


class TestPkgcheckScan(object):

    script = partial(run, project)
    fakerepo = pjoin(const.DATA_PATH, 'fakerepo')

    def test_unknown_repo(self, capsys):
        for opt in ('-r', '--repo'):
            with patch('sys.argv', [project, 'scan', opt, 'foo']):
                with raises(SystemExit) as excinfo:
                    self.script()
                assert excinfo.value.code == 2
                out, err = capsys.readouterr()
                err = err.strip().split('\n')
                assert err[-1].startswith(
                    "pkgcheck scan: error: argument -r/--repo: couldn't find repo 'foo'")

    def test_unknown_reporter(self, capsys):
        for opt in ('-R', '--reporter'):
            with patch('sys.argv', [project, 'scan', opt, 'foo', '--repo', self.fakerepo]):
                with raises(SystemExit) as excinfo:
                    self.script()
                assert excinfo.value.code == 2
                out, err = capsys.readouterr()
                err = err.strip().split('\n')
                assert err[-1].startswith(
                    "pkgcheck scan: error: no reporter matches 'foo'")

    def test_unknown_scope(self, capsys):
        for opt in ('-S', '--scopes'):
            with patch('sys.argv', [project, 'scan', opt, 'foo', '--repo', self.fakerepo]):
                with raises(SystemExit) as excinfo:
                    self.script()
                assert excinfo.value.code == 2
                out, err = capsys.readouterr()
                err = err.strip().split('\n')
                assert err[-1].startswith("pkgcheck scan: error: unknown scope: 'foo'")


class TestPkgcheckShow(object):

    script = partial(run, project)

    def test_show_keywords(self, capsys):
        # regular mode
        with patch('sys.argv', [project, 'show', '--keywords']):
            with raises(SystemExit) as excinfo:
                self.script()
            out, err = capsys.readouterr()
            assert not err
            out = out.strip().split('\n')
            regular_output = out
            assert out == sorted(x.__name__ for x in pkgcheck._known_keywords)
            assert excinfo.value.code == 0

        # verbose mode
        with patch('sys.argv', [project, 'show', '--keywords', '-v']):
            with raises(SystemExit) as excinfo:
                self.script()
            out, err = capsys.readouterr()
            assert not err
            out = out.strip().split('\n')
            verbose_output = out
            assert excinfo.value.code == 0

        # verbose output shows much more info
        assert len(regular_output) < len(verbose_output)

    def test_show_checks(self, capsys):
        # regular mode
        with patch('sys.argv', [project, 'show', '--checks']):
            with raises(SystemExit) as excinfo:
                self.script()
            out, err = capsys.readouterr()
            assert not err
            out = out.strip().split('\n')
            regular_output = out
            assert out == sorted(x.__name__ for x in pkgcheck._known_checks)
            assert excinfo.value.code == 0

        # verbose mode
        with patch('sys.argv', [project, 'show', '--checks', '-v']):
            with raises(SystemExit) as excinfo:
                self.script()
            out, err = capsys.readouterr()
            assert not err
            out = out.strip().split('\n')
            verbose_output = out
            assert excinfo.value.code == 0

        # verbose output shows much more info
        assert len(regular_output) < len(verbose_output)

    def test_show_scopes(self, capsys):
        with patch('sys.argv', [project, 'show', '--scopes']):
            with raises(SystemExit) as excinfo:
                self.script()
            out, err = capsys.readouterr()
            assert not err
            out = out.strip().split('\n')
            assert out == list(base.known_scopes)
            assert excinfo.value.code == 0

    def test_show_reporters(self, capsys):
        # regular mode
        with patch('sys.argv', [project, 'show', '--reporters']):
            with raises(SystemExit) as excinfo:
                self.script()
            out, err = capsys.readouterr()
            assert not err
            out = out.strip().split('\n')
            regular_output = out
            assert out == sorted(x.__name__ for x in get_plugins('reporter', plugins))
            assert excinfo.value.code == 0

        # verbose mode
        with patch('sys.argv', [project, 'show', '--reporters', '-v']):
            with raises(SystemExit) as excinfo:
                self.script()
            out, err = capsys.readouterr()
            assert not err
            out = out.strip().split('\n')
            verbose_output = out
            assert excinfo.value.code == 0

        # verbose output shows much more info
        assert len(regular_output) < len(verbose_output)


class TestPkgcheckReplay(object):

    script = partial(run, project)

    def test_missing_reporter_arg(self, capsys, tmp_path):
        pickle_file = tmp_path / 'empty.pickle'
        pickle_file.touch()
        with patch('sys.argv', [project, 'replay', str(pickle_file)]):
            with raises(SystemExit) as excinfo:
                self.script()
            out, err = capsys.readouterr()
            assert not out
            err = err.strip().split('\n')
            assert len(err) == 1
            assert err[0] == (
                'pkgcheck replay: error: the following arguments are required: reporter')
            assert excinfo.value.code == 2
