from functools import partial
from unittest.mock import patch

from pkgcore import const
from pytest import raises
from snakeoil.osutils import pjoin

from pkgcheck import __title__ as project
from pkgcheck.scripts import run


def test_script_run(capfd):
    """Test regular code path for running scripts."""
    script = partial(run, project)

    with patch(f'{project}.scripts.import_module') as import_module:
        import_module.side_effect = ImportError("baz module doesn't exist")

        # default error path when script import fails
        with patch('sys.argv', [project]):
            with raises(SystemExit) as excinfo:
                script()
            assert excinfo.value.code == 1
            out, err = capfd.readouterr()
            err = err.strip().split('\n')
            assert len(err) == 3
            assert err[0] == "Failed importing: baz module doesn't exist!"
            assert err[1].startswith(f"Verify that {project} and its deps")
            assert err[2] == "Add --debug to the commandline for a traceback."

        # running with --debug should raise an ImportError when there are issues
        with patch('sys.argv', [project, '--debug']):
            with raises(ImportError):
                script()
            out, err = capfd.readouterr()
            err = err.strip().split('\n')
            assert len(err) == 2
            assert err[0] == "Failed importing: baz module doesn't exist!"
            assert err[1].startswith(f"Verify that {project} and its deps")

        import_module.reset_mock()


class TestPkgcheckScan(object):

    script = partial(run, project)
    fakerepo = pjoin(const.DATA_PATH, 'fakerepo')

    def test_unknown_repo(self, capfd):
        for opt in ('-r', '--repo'):
            with patch('sys.argv', ['scan', opt, 'foo']):
                with raises(SystemExit) as excinfo:
                    self.script()
                assert excinfo.value.code == 2
                out, err = capfd.readouterr()
                err = err.strip().split('\n')
                assert err[-1].startswith(
                    "pkgcheck scan: error: argument -r/--repo: couldn't find repo 'foo'")

    def test_unknown_reporter(self, capfd):
        for opt in ('-R', '--reporter'):
            with patch('sys.argv', ['scan', opt, 'foo', '--repo', self.fakerepo]):
                with raises(SystemExit) as excinfo:
                    self.script()
                assert excinfo.value.code == 2
                out, err = capfd.readouterr()
                err = err.strip().split('\n')
                assert err[-1].startswith(
                    "pkgcheck scan: error: no reporter matches 'foo'")

    def test_unknown_scope(self, capfd):
        for opt in ('-S', '--scopes'):
            with patch('sys.argv', ['scan', opt, 'foo', '--repo', self.fakerepo]):
                with raises(SystemExit) as excinfo:
                    self.script()
                assert excinfo.value.code == 2
                out, err = capfd.readouterr()
                err = err.strip().split('\n')
                assert err[-1].startswith("pkgcheck scan: error: unknown scope: 'foo'")
