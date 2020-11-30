import argparse
import io
import os
import shlex
import shutil
import subprocess
import tempfile
import textwrap
from collections import defaultdict
from functools import partial
from io import StringIO
from operator import attrgetter
from unittest.mock import patch

import pytest
from pkgcheck import __title__ as project
from pkgcheck import base, objects, reporters
from pkgcheck import checks as checks_mod
from pkgcheck.scripts import run
from pkgcore.ebuild import atom, restricts
from pkgcore.restrictions import packages
from snakeoil.contexts import chdir
from snakeoil.fileutils import touch
from snakeoil.formatters import PlainTextFormatter
from snakeoil.osutils import pjoin


class TestPkgcheckScanParseArgs:

    def test_skipped_checks(self, tool):
        options, _ = tool.parse_args(['scan'])
        assert options.enabled_checks
        # some checks should always be skipped by default
        assert set(options.enabled_checks) != set(objects.CHECKS.values())

    def test_enabled_check(self, tool):
        options, _ = tool.parse_args(['scan', '-c', 'PkgDirCheck'])
        assert options.enabled_checks == [checks_mod.pkgdir.PkgDirCheck]

    def test_disabled_check(self, tool):
        options, _ = tool.parse_args(['scan'])
        assert checks_mod.pkgdir.PkgDirCheck in options.enabled_checks
        options, _ = tool.parse_args(['scan', '-c=-PkgDirCheck'])
        assert options.enabled_checks
        assert checks_mod.pkgdir.PkgDirCheck not in options.enabled_checks

    def test_targets(self, tool):
        options, _ = tool.parse_args(['scan', 'dev-util/foo'])
        assert list(options.restrictions) == [(base.package_scope, atom.atom('dev-util/foo'))]

    def test_stdin_targets(self, tool):
        with patch('sys.stdin', StringIO('dev-util/foo')):
            options, _ = tool.parse_args(['scan', '-'])
            assert list(options.restrictions) == [(base.package_scope, atom.atom('dev-util/foo'))]

    def test_stdin_targets_with_no_args(self, tool, capsys):
        with patch('sys.stdin', StringIO()):
            with pytest.raises(SystemExit) as excinfo:
                tool.parse_args(['scan', '-'])
                assert excinfo.value.code == 2
                out, err = capsys.readouterr()
                err = err.strip().split('\n')
                assert err[-1] == 'no targets piped in'

    def test_invalid_targets(self, tool, capsys):
        with pytest.raises(SystemExit) as excinfo:
            options, _ = tool.parse_args(['scan', 'dev-util/f$o'])
        assert excinfo.value.code == 2
        out, err = capsys.readouterr()
        err = err.strip()
        assert err == "pkgcheck scan: error: invalid package atom: 'dev-util/f$o'"

    def test_unknown_path_target(self, tool, capsys):
        with pytest.raises(SystemExit) as excinfo:
            tool.parse_args(['scan', '/foo/bar'])
        assert excinfo.value.code == 2
        out, err = capsys.readouterr()
        err = err.strip().split('\n')
        assert err[-1].startswith(
            "pkgcheck scan: error: 'stubrepo' repo doesn't contain: '/foo/bar'")

    def test_target_repo_id(self, tool):
        options, _ = tool.parse_args(['scan', '-r', 'stubrepo'])
        assert options.target_repo.repo_id == 'stubrepo'
        assert list(options.restrictions) == [(base.repo_scope, packages.AlwaysTrue)]

    def test_target_dir_path(self, repo, tool):
        # dir path
        options, _ = tool.parse_args(['scan', repo.location])
        assert options.target_repo.repo_id == 'fake'
        assert list(options.restrictions) == [(base.repo_scope, packages.AlwaysTrue)]

    def test_target_file_path(self, repo, tool):
        os.makedirs(pjoin(repo.location, 'dev-util', 'foo'))
        ebuild_path = pjoin(repo.location, 'dev-util', 'foo', 'foo-0.ebuild')
        touch(ebuild_path)
        options, _ = tool.parse_args(['scan', ebuild_path])
        restrictions = [
            restricts.CategoryDep('dev-util'),
            restricts.PackageDep('foo'),
            restricts.VersionMatch('=', '0'),
        ]
        assert list(options.restrictions) == [(base.version_scope, packages.AndRestriction(*restrictions))]
        assert options.target_repo.repo_id == 'fake'

    def test_target_package_dir_cwd(self, repo, tool):
        os.makedirs(pjoin(repo.location, 'dev-util', 'foo'))
        with chdir(pjoin(repo.location, 'dev-util', 'foo')):
            options, _ = tool.parse_args(['scan'])
            assert options.target_repo.repo_id == 'fake'
            restrictions = [
                restricts.CategoryDep('dev-util'),
                restricts.PackageDep('foo'),
            ]
            assert list(options.restrictions) == [(base.package_scope, packages.AndRestriction(*restrictions))]

    def test_target_repo_dir_cwd(self, repo, tool):
        with chdir(repo.location):
            options, _ = tool.parse_args(['scan'])
            assert options.target_repo.repo_id == 'fake'
            assert list(options.restrictions) == [(base.repo_scope, packages.AlwaysTrue)]

    def test_unknown_repo(self, tmp_path, capsys, tool):
        for opt in ('-r', '--repo'):
            with pytest.raises(SystemExit) as excinfo:
                with chdir(str(tmp_path)):
                    options, _ = tool.parse_args(['scan', opt, 'foo'])
            assert excinfo.value.code == 2
            out, err = capsys.readouterr()
            err = err.strip().split('\n')
            assert err[-1].startswith(
                "pkgcheck scan: error: argument -r/--repo: couldn't find repo 'foo'")

    def test_invalid_repo(self, tmp_path, capsys, tool):
        touch(pjoin(str(tmp_path), 'foo'))
        for opt in ('-r', '--repo'):
            with pytest.raises(SystemExit) as excinfo:
                with chdir(str(tmp_path)):
                    options, _ = tool.parse_args(['scan', opt, 'foo'])
            assert excinfo.value.code == 2
            out, err = capsys.readouterr()
            err = err.strip().split('\n')
            assert err[-1].startswith(
                "pkgcheck scan: error: argument -r/--repo: invalid repo")

    def test_unknown_reporter(self, capsys, tool):
        for opt in ('-R', '--reporter'):
            with pytest.raises(SystemExit) as excinfo:
                options, _ = tool.parse_args(['scan', opt, 'foo'])
            assert excinfo.value.code == 2
            out, err = capsys.readouterr()
            err = err.strip().split('\n')
            assert err[-1].startswith(
                "pkgcheck scan: error: no reporter matches 'foo'")

    def test_format_reporter(self, capsys, tool):
        # missing --format
        with pytest.raises(SystemExit) as excinfo:
            tool.parse_args(['scan', '-R', 'FormatReporter'])
        assert excinfo.value.code == 2
        out, err = capsys.readouterr()
        err = err.strip().split('\n')
        assert err[-1].endswith(
            "missing or empty --format option required by FormatReporter")

        # missing -R FormatReporter
        with pytest.raises(SystemExit) as excinfo:
            tool.parse_args(['scan', '--format', 'foo'])
        assert excinfo.value.code == 2
        out, err = capsys.readouterr()
        err = err.strip().split('\n')
        assert err[-1].endswith(
            "--format option is only valid when using FormatReporter")

        # properly set
        options, _ = tool.parse_args(
            ['scan', '-R', 'FormatReporter', '--format', 'foo'])

    def test_cwd(self, capsys, tool):
        # regularly working
        options, _ = tool.parse_args(['scan', 'cat/pkg'])
        assert options.cwd == os.getcwd()

        # pretend the CWD was removed out from under us
        with patch('os.getcwd') as getcwd:
            getcwd.side_effect = FileNotFoundError('CWD is gone')
            options, _ = tool.parse_args(['scan', 'cat/pkg'])
            assert options.cwd == '/'

    def test_conflicting_scan_scopes(self, capsys, fakerepo, tool):
        """Multiple targets can't specify different scopes."""
        with pytest.raises(SystemExit) as excinfo:
            tool.parse_args(['scan', fakerepo, 'cat/pkg'])
        assert excinfo.value.code == 2
        out, err = capsys.readouterr()
        err = err.strip().split('\n')
        assert err[-1].startswith(
            "pkgcheck scan: error: targets specify multiple scan scope levels: package, repo")

    def test_collapsed_restrictions(self, tool):
        """Multiple targets get collapsed into one restriction to run in parallel."""
        options, _ = tool.parse_args(['scan', 'cat/pkg1', 'cat/pkg2'])
        scope, restrict = list(options.restrictions)[0]
        assert scope is base.package_scope
        assert restrict.restrictions == (atom.atom('cat/pkg1'), atom.atom('cat/pkg2'))

    def test_eclass_target(self, fakerepo, tool):
        os.makedirs(pjoin(fakerepo, 'eclass'))
        eclass_path = pjoin(fakerepo, 'eclass', 'foo.eclass')
        touch(eclass_path)
        options, _ = tool.parse_args(['scan', eclass_path])
        scope, restrict = list(options.restrictions)[0]
        assert scope == base.eclass_scope

    def test_profiles_target(self, fakerepo, tool):
        profiles_path = pjoin(fakerepo, 'profiles')
        options, _ = tool.parse_args(['scan', profiles_path])
        assert list(options.restrictions) == [(base.profiles_scope, packages.AlwaysTrue)]

    def test_argparse_error(self, capsys, tool):
        """Argparse errors are used for error mesages under normal operation."""
        action = argparse.Action(['--foo'], 'foo')
        with patch('pkgcheck.addons.ProfileAddon.check_args') as check_args:
            check_args.side_effect = argparse.ArgumentError(action, 'invalid arg')
            with pytest.raises(SystemExit) as excinfo:
                tool.parse_args(['scan', 'cat/pkg'])
            assert excinfo.value.code == 2
            out, err = capsys.readouterr()
            err = err.strip().split('\n')
            assert err[-1].startswith('pkgcheck scan: error: argument --foo: invalid arg')

    def test_argparse_error_debug(self, capsys, tool):
        """Argparse errors are raised when parsing args under debug mode."""
        action = argparse.Action(['--foo'], 'foo')
        with patch('pkgcheck.addons.ProfileAddon.check_args') as check_args:
            check_args.side_effect = argparse.ArgumentError(action, 'invalid arg')
            with pytest.raises(argparse.ArgumentError):
                tool.parse_args(['scan', '--debug', 'cat/pkg'])


class TestPkgcheckScanParseConfigArgs:

    @pytest.fixture(autouse=True)
    def _setup(self, tool, tmp_path, repo):
        self.tool = tool
        self.repo = repo
        self.args = ['scan', '-r', repo.location]

        # override system/user config locations
        self.system_config = str(tmp_path / "system-config")
        self.user_config = str(tmp_path / "user-config")
        self.config = str(tmp_path / "custom-config")
        self.scan_parser = self.tool.parser.subparsers['scan']
        self.scan_parser.configs = (self.system_config, self.user_config)

    def test_config_precedence(self):
        with open(self.system_config, 'w') as f:
            f.write(textwrap.dedent("""\
                [DEFAULT]
                jobs=1000
            """))
        options, _ = self.tool.parse_args(self.args)
        assert options.jobs == 1000

        # user config overrides system config
        with open(self.user_config, 'w') as f:
            f.write(textwrap.dedent("""\
                [DEFAULT]
                jobs=1001
            """))
        # reset config obj jit attr
        self.scan_parser._config = None
        options, _ = self.tool.parse_args(self.args)
        assert options.jobs == 1001

        # repo config overrides user config
        with open(pjoin(self.repo.location, 'metadata', 'pkgcheck.conf'), 'w') as f:
            f.write(textwrap.dedent("""\
                [DEFAULT]
                jobs=1002
            """))
        options, _ = self.tool.parse_args(self.args)
        assert options.jobs == 1002

        # custom config overrides user config
        with open(self.config, 'w') as f:
            f.write(textwrap.dedent("""\
                [DEFAULT]
                jobs=1003
            """))
        config_args = self.args + ['--config', self.config]
        options, _ = self.tool.parse_args(config_args)
        assert options.jobs == 1003

        # repo defaults override general defaults
        with open(self.config, 'a') as f:
            f.write(textwrap.dedent(f"""\
                [{self.repo.repo_id}]
                jobs=1004
            """))
        options, _ = self.tool.parse_args(config_args)
        assert options.jobs == 1004

        # command line options override all config settings
        options, _ = self.tool.parse_args(config_args + ['--jobs', '9999'])
        assert options.jobs == 9999


class TestPkgcheckScan:

    script = partial(run, project)

    testdir = os.path.dirname(os.path.dirname(__file__))
    repos_data = pjoin(testdir, 'data', 'repos')
    repos_dir = pjoin(testdir, 'repos')
    repos = tuple(x for x in sorted(os.listdir(repos_data)) if x != 'network')

    _all_results = []
    for name, cls in sorted(objects.CHECKS.items()):
        if not issubclass(cls, checks_mod.NetworkCheck):
            for result in sorted(cls.known_results, key=attrgetter('__name__')):
                _all_results.append((cls, result))

    @pytest.fixture(autouse=True)
    def _setup(self, testconfig, tmp_path):
        self.cache_dir = str(tmp_path)
        self.args = [
            project, '--config', testconfig,
            'scan', '--config', 'no', '--cache-dir', self.cache_dir,
        ]

    @staticmethod
    def _patch(fix, repo_path):
        with open(fix) as f:
            p = subprocess.run(
                ['patch', '-p1'], cwd=repo_path, stdout=subprocess.DEVNULL, stdin=f)
            p.check_returncode()

    @staticmethod
    def _script(fix, repo_path):
        p = subprocess.run([fix], cwd=repo_path)
        p.check_returncode()

    def test_empty_repo(self, capsys):
        # no reports should be generated since the default repo is empty
        with patch('sys.argv', self.args):
            with pytest.raises(SystemExit) as excinfo:
                self.script()
            assert excinfo.value.code == 0
            out, err = capsys.readouterr()
            assert out == err == ''

    def test_explict_skip_check(self, capsys):
        """SkipCheck exceptions are raised when triggered for explicitly enabled checks."""
        with patch('sys.argv', self.args + ['-c', 'net']):
            with pytest.raises(SystemExit) as excinfo:
                self.script()
            assert excinfo.value.code == 2
            out, err = capsys.readouterr()
            assert not out
            assert 'network checks not enabled' in err

    @pytest.mark.parametrize(
        'action, module',
        (('queue', 'UnversionedSource'), ('run', 'CheckRunner.run')))
    def test_pipeline_exceptions(self, action, module, capsys):
        """Test checkrunner pipeline against unhandled exceptions."""
        with patch('sys.argv', self.args), \
                patch(f'pkgcheck.pipeline.{module}') as faked:
            faked.side_effect = Exception('foobar')
            with pytest.raises(SystemExit) as excinfo:
                self.script()
            assert excinfo.value.code == 1
            out, err = capsys.readouterr()
            assert out == ''
            assert err.splitlines()[-1] == 'Exception: foobar'

    # nested mapping of repos to checks/keywords they cover
    _checks = defaultdict(lambda: defaultdict(set))

    @pytest.mark.parametrize('repo', repos)
    def test_scan_repo_data(self, repo):
        """Make sure the test data is up to date check/result naming wise."""
        for check in os.listdir(pjoin(self.repos_data, repo)):
            assert check in objects.CHECKS
            for keyword in os.listdir(pjoin(self.repos_data, repo, check)):
                assert keyword in objects.KEYWORDS
                self._checks[repo][check].add(keyword)

    # mapping of repos to scanned results
    _results = {}
    _verbose_results = {}

    @pytest.mark.parametrize('repo', repos)
    def test_scan_repo(self, repo, capsysbinary, tmp_path, verbosity=0):
        """Scan a target repo, saving results for verfication."""
        repo_dir = pjoin(self.repos_dir, repo)

        # run all existing triggers
        triggers = []
        for root, _dirs, files in os.walk(pjoin(self.repos_data, repo)):
            for f in (x for x in files if x == 'trigger.sh'):
                triggers.append(pjoin(root, f))
        if triggers:
            triggered_repo = str(tmp_path / f'triggered-{repo}')
            shutil.copytree(repo_dir, triggered_repo)
            for trigger in triggers:
                self._script(trigger, triggered_repo)
            repo_dir = triggered_repo

        args = (['-v'] * verbosity) + ['-r', repo_dir, '-c', ','.join(self._checks[repo])]

        # add any defined extra repo args
        try:
            with open(f'{repo_dir}/metadata/pkgcheck-args') as f:
                args.extend(shlex.split(f.read()))
        except FileNotFoundError:
            pass

        results = []
        verbose_results = []
        with patch('sys.argv', self.args + ['-R', 'BinaryPickleStream'] + args):
            with pytest.raises(SystemExit) as excinfo:
                self.script()
            out, err = capsysbinary.readouterr()
            assert out, f'{repo} repo failed, no results'
            assert excinfo.value.code == 0
            for result in reporters.BinaryPickleStream.from_file(io.BytesIO(out)):
                # ignore results generated from stubs
                stubs = (getattr(result, x, '') for x in ('category', 'package'))
                if any(x.startswith('stub') for x in stubs):
                    continue
                if verbosity:
                    verbose_results.append(result)
                else:
                    results.append(result)

        if verbosity:
            self._verbose_results[repo] = set(verbose_results)
            assert len(verbose_results) == len(self._verbose_results[repo])
        else:
            self._results[repo] = set(results)
            assert len(results) == len(self._results[repo])

    @pytest.mark.parametrize('repo', repos)
    def test_scan_repo_verbose(self, repo, capsysbinary, tmp_path):
        """Scan a target repo in verbose mode, saving results for verfication."""
        return self.test_scan_repo(repo, capsysbinary, tmp_path, verbosity=1)

    def _get_results(self, path):
        """Return the set of result objects from a given json stream file."""
        try:
            with open(pjoin(self.repos_data, path)) as f:
                return set(reporters.JsonStream.from_iter(f))
        except FileNotFoundError:
            return set()

    def _render_results(self, results, **kwargs):
        """Render a given set of result objects into their related string form."""
        with tempfile.TemporaryFile() as f:
            with reporters.FancyReporter(out=PlainTextFormatter(f), **kwargs) as reporter:
                for result in sorted(results):
                    reporter.report(result)
            f.seek(0)
            output = f.read().decode()
            return output

    @pytest.mark.parametrize('repo', repos)
    def test_scan_verify(self, repo, capsys, tmp_path):
        """Run pkgcheck against test pkgs in bundled repo, verifying result output."""
        results = set()
        verbose_results = set()
        for check, keywords in self._checks[repo].items():
            for keyword in keywords:
                # verify the expected results were seen during the repo scans
                expected_results = self._get_results(f'{repo}/{check}/{keyword}/expected.json')
                assert expected_results, 'regular results must always exist'
                assert self._render_results(expected_results), 'failed rendering results'
                results.update(expected_results)

                # when expected verbose results exist use them, otherwise fallback to using the regular ones
                expected_verbose_results = self._get_results(f'{repo}/{check}/{keyword}/expected-verbose.json')
                if expected_verbose_results:
                    assert self._render_results(expected_verbose_results), 'failed rendering verbose results'
                    verbose_results.update(expected_verbose_results)
                else:
                    verbose_results.update(expected_results)

        if results != self._results[repo]:
            missing = self._render_results(results - self._results[repo])
            if missing:
                pytest.fail(f'{repo} repo missing expected results:\n{missing}')
            unknown = self._render_results(self._results[repo] - results)
            if unknown:
                pytest.fail(f'{repo} repo unknown results:\n{unknown}')
        if verbose_results != self._verbose_results[repo]:
            missing = self._render_results(verbose_results - self._verbose_results[repo])
            if missing:
                pytest.fail(f'{repo} repo missing expected verbose results:\n{missing}')
            unknown = self._render_results(self._verbose_results[repo] - verbose_results)
            if unknown:
                pytest.fail(f'{repo} repo unknown verbose results:\n{unknown}')

    @pytest.mark.parametrize('check, result', _all_results)
    def test_scan_fix(self, check, result, capsys, tmp_path):
        """Apply fixes to pkgs, verifying the related results are fixed."""
        check_name = check.__name__
        keyword = result.__name__
        tested = False
        for repo in self.repos:
            keyword_dir = pjoin(self.repos_data, f'{repo}/{check_name}/{keyword}')
            if os.path.exists(pjoin(keyword_dir, 'fix.patch')):
                fix = pjoin(keyword_dir, 'fix.patch')
                func = self._patch
            elif os.path.exists(pjoin(keyword_dir, 'fix.sh')):
                fix = pjoin(keyword_dir, 'fix.sh')
                func = self._script
            else:
                continue

            # apply a fix if one exists and make sure the related result doesn't appear
            repo_dir = pjoin(self.repos_dir, repo)
            fixed_repo = str(tmp_path / f'fixed-{repo}')
            shutil.copytree(repo_dir, fixed_repo)
            func(fix, fixed_repo)

            args = ['-r', fixed_repo, '-c', check_name, '-k', keyword]

            # add any defined extra repo args
            try:
                with open(f'{repo_dir}/metadata/pkgcheck-args') as f:
                    args.extend(shlex.split(f.read()))
            except FileNotFoundError:
                pass

            cmd = self.args + args
            with patch('sys.argv', cmd):
                with pytest.raises(SystemExit) as excinfo:
                    self.script()
                out, err = capsys.readouterr()
                assert not err, f"failed fixing error, command: {' '.join(cmd)}"
                assert not out, f"failed fixing error, command: {' '.join(cmd)}"
                assert excinfo.value.code == 0
            shutil.rmtree(fixed_repo)
            tested = True

        if not tested:
            pytest.skip('fix not available')
