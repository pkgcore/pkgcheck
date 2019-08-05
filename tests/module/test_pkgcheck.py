from functools import partial
from io import StringIO
import textwrap
from unittest.mock import patch

from pkgcore import const
from pkgcore.plugin import get_plugins
from pkgcore.util.commandline import Tool
import pytest
from snakeoil.osutils import pjoin

from pkgcheck import base, checks, plugins, __title__ as project
from pkgcheck.scripts import run, pkgcheck


@pytest.fixture
def fakeconfig(tmp_path):
    """Generate a portage config that sets the default repo to pkgcore's fakerepo."""
    fakeconfig = str(tmp_path)
    repos_conf = tmp_path / 'repos.conf'
    fakerepo = pjoin(const.DATA_PATH, 'fakerepo')
    with open(repos_conf, 'w') as f:
        f.write(textwrap.dedent(f"""\
            [DEFAULT]
            main-repo = fakerepo

            [fakerepo]
            location = {fakerepo}"""))
    return fakeconfig


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


class TestPkgcheckScanParseArgs(object):

    @pytest.fixture(autouse=True)
    def _setup(self, fakeconfig):
        self.tool = Tool(pkgcheck.argparser)
        self.tool.parser.set_defaults(override_config=fakeconfig)
        self.args = ['scan']

    def test_skipped_checks(self):
        options, _func = self.tool.parse_args(self.args)
        assert options.enabled_checks
        # some checks should always be skipped by default
        assert set(options.enabled_checks) != set(pkgcheck._known_checks)

    def test_enabled_check(self):
        options, _func = self.tool.parse_args(self.args + ['-c', 'PkgDirCheck'])
        assert options.enabled_checks == [checks.pkgdir.PkgDirCheck]

    def test_disabled_check(self):
        options, _func = self.tool.parse_args(self.args)
        assert checks.pkgdir.PkgDirCheck in options.enabled_checks
        options, _func = self.tool.parse_args(self.args + ['-c=-PkgDirCheck'])
        assert options.enabled_checks
        assert checks.pkgdir.PkgDirCheck not in options.enabled_checks

    def test_targets(self):
        options, _func = self.tool.parse_args(self.args + ['dev-util/foo'])
        assert options.targets == ['dev-util/foo']

    def test_stdin_targets(self):
        with patch('sys.stdin', StringIO('dev-util/foo')):
            options, _func = self.tool.parse_args(self.args + ['-'])
            assert list(options.targets) == ['dev-util/foo']


class TestPkgcheckScan(object):

    script = partial(run, project)

    @pytest.fixture(autouse=True)
    def _setup(self, fakeconfig):
        self.args = [project, '--config', fakeconfig, 'scan']

    def test_unknown_repo(self, capsys):
        for opt in ('-r', '--repo'):
            with patch('sys.argv', self.args + [opt, 'foo']):
                with pytest.raises(SystemExit) as excinfo:
                    self.script()
                assert excinfo.value.code == 2
                out, err = capsys.readouterr()
                err = err.strip().split('\n')
                assert err[-1].startswith(
                    "pkgcheck scan: error: argument -r/--repo: couldn't find repo 'foo'")

    def test_unknown_reporter(self, capsys):
        for opt in ('-R', '--reporter'):
            with patch('sys.argv', self.args + [opt, 'foo']):
                with pytest.raises(SystemExit) as excinfo:
                    self.script()
                assert excinfo.value.code == 2
                out, err = capsys.readouterr()
                err = err.strip().split('\n')
                assert err[-1].startswith(
                    "pkgcheck scan: error: no reporter matches 'foo'")

    def test_unknown_scope(self, capsys):
        for opt in ('-S', '--scopes'):
            with patch('sys.argv', self.args + [opt, 'foo']):
                with pytest.raises(SystemExit) as excinfo:
                    self.script()
                assert excinfo.value.code == 2
                out, err = capsys.readouterr()
                err = err.strip().split('\n')
                assert err[-1].startswith("pkgcheck scan: error: unknown scope: 'foo'")

    def test_unknown_check(self, capsys):
        for opt in ('-c', '--checks'):
            with patch('sys.argv', self.args + [opt, 'foo']):
                with pytest.raises(SystemExit) as excinfo:
                    self.script()
                assert excinfo.value.code == 2
                out, err = capsys.readouterr()
                err = err.strip().split('\n')
                assert err[-1].startswith("pkgcheck scan: error: unknown check: 'foo'")

    def test_unknown_keyword(self, capsys):
        for opt in ('-k', '--keywords'):
            with patch('sys.argv', self.args + [opt, 'foo']):
                with pytest.raises(SystemExit) as excinfo:
                    self.script()
                assert excinfo.value.code == 2
                out, err = capsys.readouterr()
                err = err.strip().split('\n')
                assert err[-1].startswith("pkgcheck scan: error: unknown keyword: 'foo'")

    def test_missing_scope(self, capsys):
        for opt in ('-S', '--scopes'):
            with patch('sys.argv', self.args + [opt]):
                with pytest.raises(SystemExit) as excinfo:
                    self.script()
                assert excinfo.value.code == 2
                out, err = capsys.readouterr()
                err = err.strip().split('\n')
                assert err[0] == (
                    'pkgcheck scan: error: argument -S/--scopes: expected one argument')

    def test_empty_repo(self, capsys):
        # no reports should be generated since the default repo is empty
        with patch('sys.argv', self.args):
            with pytest.raises(SystemExit) as excinfo:
                self.script()
            assert excinfo.value.code == 0
            out, err = capsys.readouterr()
            assert out == err == ''

    def test_no_active_checks(self, capsys):
        with patch('sys.argv', self.args + ['-c', 'UnusedInMastersCheck']):
            with pytest.raises(SystemExit) as excinfo:
                self.script()
            assert excinfo.value.code == 2
            out, err = capsys.readouterr()
            err = err.strip().split('\n')
            assert err[-1].startswith("pkgcheck scan: error: no active checks")


class TestPkgcheckShow(object):

    script = partial(run, project)

    @pytest.fixture(autouse=True)
    def _setup(self, fakeconfig):
        self.args = [project, '--config', fakeconfig, 'show']

    def test_show_no_args(self, capsys):
        # defaults to outputting keywords list if no option is passed
        with patch('sys.argv', self.args):
            with pytest.raises(SystemExit) as excinfo:
                self.script()
            out, err = capsys.readouterr()
            assert not err
            out = out.strip().split('\n')
            regular_output = out
            assert out == sorted(x.__name__ for x in pkgcheck._known_keywords)
            assert excinfo.value.code == 0

    def test_show_keywords(self, capsys):
        # regular mode
        with patch('sys.argv', self.args + ['--keywords']):
            with pytest.raises(SystemExit) as excinfo:
                self.script()
            out, err = capsys.readouterr()
            assert not err
            out = out.strip().split('\n')
            regular_output = out
            assert out == sorted(x.__name__ for x in pkgcheck._known_keywords)
            assert excinfo.value.code == 0

        # verbose mode
        with patch('sys.argv', self.args + ['--keywords', '-v']):
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
        # regular mode
        with patch('sys.argv', self.args + ['--checks']):
            with pytest.raises(SystemExit) as excinfo:
                self.script()
            out, err = capsys.readouterr()
            assert not err
            out = out.strip().split('\n')
            regular_output = out
            assert out == sorted(x.__name__ for x in pkgcheck._known_checks)
            assert excinfo.value.code == 0

        # verbose mode
        with patch('sys.argv', self.args + ['--checks', '-v']):
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
        with patch('sys.argv', self.args + ['--scopes']):
            with pytest.raises(SystemExit) as excinfo:
                self.script()
            out, err = capsys.readouterr()
            assert not err
            out = out.strip().split('\n')
            assert out == list(base.known_scopes)
            assert excinfo.value.code == 0

    def test_show_reporters(self, capsys):
        # regular mode
        with patch('sys.argv', self.args + ['--reporters']):
            with pytest.raises(SystemExit) as excinfo:
                self.script()
            out, err = capsys.readouterr()
            assert not err
            out = out.strip().split('\n')
            regular_output = out
            assert out == sorted(x.__name__ for x in get_plugins('reporter', plugins))
            assert excinfo.value.code == 0

        # verbose mode
        with patch('sys.argv', self.args + ['--reporters', '-v']):
            with pytest.raises(SystemExit) as excinfo:
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

    @pytest.fixture(autouse=True)
    def _setup(self, fakeconfig):
        self.args = [project, '--config', fakeconfig, 'replay']

    def test_missing_reporter_arg(self, capsys, tmp_path):
        pickle_file = tmp_path / 'empty.pickle'
        pickle_file.touch()
        with patch('sys.argv', self.args + [str(pickle_file)]):
            with pytest.raises(SystemExit) as excinfo:
                self.script()
            out, err = capsys.readouterr()
            assert not out
            err = err.strip().split('\n')
            assert len(err) == 1
            assert err[0] == (
                'pkgcheck replay: error: the following arguments are required: reporter')
            assert excinfo.value.code == 2
