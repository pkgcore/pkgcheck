import importlib
from functools import partial
from unittest.mock import patch

import pytest
from pkgcheck import __title__ as project
from pkgcheck.scripts import run


def test_script_run(capsys):
    """Test regular code path for running scripts."""
    script = partial(run, project)

    with patch(f'{project}.scripts.import_module') as import_module:
        import_module.side_effect = ImportError("baz module doesn't exist")

        # default error path when script import fails
        with patch('sys.argv', [project]):
            with pytest.raises(SystemExit) as excinfo:
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
            with pytest.raises(ImportError):
                script()
            out, err = capsys.readouterr()
            err = err.strip().split('\n')
            assert len(err) == 2
            assert err[0] == "Failed importing: baz module doesn't exist!"
            assert err[1].startswith(f"Verify that {project} and its deps")

        import_module.reset_mock()


class TestPkgcheck:

    script = partial(run, project)

    def test_version(self, capsys):
        with patch('sys.argv', [project, '--version']):
            with pytest.raises(SystemExit) as excinfo:
                self.script()
            assert excinfo.value.code == 0
            out, err = capsys.readouterr()
            assert out.startswith(project)

    def test_installed(self):
        """Verify tests are running in environment where generated modules exist."""
        try:
            importlib.import_module(f'{project}._verinfo')
        except ImportError:
            pytest.fail(
                'not running against installed or released package\n'
                '(use `setup.py test` when running from git)'
            )
