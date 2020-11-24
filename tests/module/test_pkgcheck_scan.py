import argparse
import io
import os
import shlex
import shutil
import subprocess
import tempfile
from collections import defaultdict
from functools import partial
from io import StringIO
from operator import attrgetter
from unittest.mock import patch

import pytest
from pkgcheck import __title__ as project
from pkgcheck import base, objects, reporters, results
from pkgcheck import checks as checks_mod
from pkgcheck.scripts import run
from pkgcore import const as pkgcore_const
from pkgcore.ebuild import atom, restricts
from pkgcore.restrictions import packages
from snakeoil.contexts import chdir
from snakeoil.fileutils import touch
from snakeoil.formatters import PlainTextFormatter
from snakeoil.osutils import pjoin


class TestPkgcheckScanParseArgs:

    @pytest.fixture(autouse=True)
    def _setup(self, tool, tmp_path):
        self.tool = tool
        self.cache_dir = str(tmp_path)
        self.args = ['scan', '--cache-dir', self.cache_dir]

    def test_skipped_checks(self):
        options, _ = self.tool.parse_args(self.args)
        assert options.enabled_checks
        # some checks should always be skipped by default
        assert set(options.enabled_checks) != set(objects.CHECKS.values())

    def test_enabled_check(self):
        options, _ = self.tool.parse_args(self.args + ['-c', 'PkgDirCheck'])
        assert options.enabled_checks == [checks_mod.pkgdir.PkgDirCheck]

    def test_disabled_check(self):
        options, _ = self.tool.parse_args(self.args)
        assert checks_mod.pkgdir.PkgDirCheck in options.enabled_checks
        options, _ = self.tool.parse_args(self.args + ['-c=-PkgDirCheck'])
        assert options.enabled_checks
        assert checks_mod.pkgdir.PkgDirCheck not in options.enabled_checks

    def test_targets(self):
        options, _ = self.tool.parse_args(self.args + ['dev-util/foo'])
        assert list(options.restrictions) == [(base.package_scope, atom.atom('dev-util/foo'))]

    def test_stdin_targets(self):
        with patch('sys.stdin', StringIO('dev-util/foo')):
            options, _ = self.tool.parse_args(self.args + ['-'])
            assert list(options.restrictions) == [(base.package_scope, atom.atom('dev-util/foo'))]

    def test_stdin_targets_with_no_args(self, capsys):
        with patch('sys.stdin', StringIO()):
            with pytest.raises(SystemExit) as excinfo:
                self.tool.parse_args(self.args + ['-'])
                assert excinfo.value.code == 2
                out, err = capsys.readouterr()
                err = err.strip().split('\n')
                assert err[-1] == 'no targets piped in'

    def test_invalid_targets(self, capsys):
        with pytest.raises(SystemExit) as excinfo:
            options, _ = self.tool.parse_args(self.args + ['dev-util/f$o'])
        assert excinfo.value.code == 2
        out, err = capsys.readouterr()
        err = err.strip()
        assert err == "pkgcheck scan: error: invalid package atom: 'dev-util/f$o'"

    def test_unknown_path_target(self, capsys):
        with pytest.raises(SystemExit) as excinfo:
            self.tool.parse_args(self.args + ['/foo/bar'])
        assert excinfo.value.code == 2
        out, err = capsys.readouterr()
        err = err.strip().split('\n')
        assert err[-1].startswith(
            "pkgcheck scan: error: 'stubrepo' repo doesn't contain: '/foo/bar'")

    def test_selected_targets(self, fakerepo):
        # selected repo
        options, _ = self.tool.parse_args(self.args + ['-r', 'stubrepo'])
        assert options.target_repo.repo_id == 'stubrepo'
        assert list(options.restrictions) == [(base.repo_scope, packages.AlwaysTrue)]

        # dir path
        options, _ = self.tool.parse_args(self.args + [fakerepo])
        assert options.target_repo.repo_id == 'fakerepo'
        assert list(options.restrictions) == [(base.repo_scope, packages.AlwaysTrue)]

        # file path
        os.makedirs(pjoin(fakerepo, 'dev-util', 'foo'))
        ebuild_path = pjoin(fakerepo, 'dev-util', 'foo', 'foo-0.ebuild')
        touch(ebuild_path)
        options, _ = self.tool.parse_args(self.args + [ebuild_path])
        restrictions = [
            restricts.CategoryDep('dev-util'),
            restricts.PackageDep('foo'),
            restricts.VersionMatch('=', '0'),
        ]
        assert list(options.restrictions) == [(base.version_scope, packages.AndRestriction(*restrictions))]
        assert options.target_repo.repo_id == 'fakerepo'

        # cwd path in unconfigured repo
        with chdir(pjoin(fakerepo, 'dev-util', 'foo')):
            options, _ = self.tool.parse_args(self.args)
            assert options.target_repo.repo_id == 'fakerepo'
            restrictions = [
                restricts.CategoryDep('dev-util'),
                restricts.PackageDep('foo'),
            ]
            assert list(options.restrictions) == [(base.package_scope, packages.AndRestriction(*restrictions))]

        # cwd path in configured repo
        stubrepo = pjoin(pkgcore_const.DATA_PATH, 'stubrepo')
        with chdir(stubrepo):
            options, _ = self.tool.parse_args(self.args)
            assert options.target_repo.repo_id == 'stubrepo'
            assert list(options.restrictions) == [(base.repo_scope, packages.AlwaysTrue)]

    def test_unknown_repo(self, capsys):
        for opt in ('-r', '--repo'):
            with pytest.raises(SystemExit) as excinfo:
                options, _ = self.tool.parse_args(self.args + [opt, 'foo'])
            assert excinfo.value.code == 2
            out, err = capsys.readouterr()
            err = err.strip().split('\n')
            assert err[-1].startswith(
                "pkgcheck scan: error: argument -r/--repo: couldn't find repo 'foo'")

    def test_unknown_reporter(self, capsys):
        for opt in ('-R', '--reporter'):
            with pytest.raises(SystemExit) as excinfo:
                options, _ = self.tool.parse_args(self.args + [opt, 'foo'])
            assert excinfo.value.code == 2
            out, err = capsys.readouterr()
            err = err.strip().split('\n')
            assert err[-1].startswith(
                "pkgcheck scan: error: no reporter matches 'foo'")

    def test_format_reporter(self, capsys):
        # missing --format
        with pytest.raises(SystemExit) as excinfo:
            self.tool.parse_args(self.args + ['-R', 'FormatReporter'])
        assert excinfo.value.code == 2
        out, err = capsys.readouterr()
        err = err.strip().split('\n')
        assert err[-1].endswith(
            "missing or empty --format option required by FormatReporter")

        # missing -R FormatReporter
        with pytest.raises(SystemExit) as excinfo:
            self.tool.parse_args(self.args + ['--format', 'foo'])
        assert excinfo.value.code == 2
        out, err = capsys.readouterr()
        err = err.strip().split('\n')
        assert err[-1].endswith(
            "--format option is only valid when using FormatReporter")

        # properly set
        options, _ = self.tool.parse_args(
            self.args + ['-R', 'FormatReporter', '--format', 'foo'])

    def test_unknown_scope(self, capsys):
        for opt in ('-s', '--scopes'):
            with pytest.raises(SystemExit) as excinfo:
                options, _ = self.tool.parse_args(self.args + [opt, 'foo'])
            assert excinfo.value.code == 2
            out, err = capsys.readouterr()
            err = err.strip().split('\n')
            assert "unknown scope: 'foo'" in err[-1]

    def test_unknown_check(self, capsys):
        for opt in ('-c', '--checks'):
            with pytest.raises(SystemExit) as excinfo:
                options, _ = self.tool.parse_args(self.args + [opt, 'foo'])
            assert excinfo.value.code == 2
            out, err = capsys.readouterr()
            err = err.strip().split('\n')
            assert "unknown check: 'foo'" in err[-1]

    def test_unknown_keyword(self, capsys):
        for opt in ('-k', '--keywords'):
            with pytest.raises(SystemExit) as excinfo:
                options, _ = self.tool.parse_args(self.args + [opt, 'foo'])
            assert excinfo.value.code == 2
            out, err = capsys.readouterr()
            err = err.strip().split('\n')
            assert "unknown keyword: 'foo'" in err[-1]

    def test_cwd(self, capsys):
        # regularly working
        options, _ = self.tool.parse_args(self.args + ['cat/pkg'])
        assert options.cwd == os.getcwd()

        # pretend the CWD was removed out from under us
        with patch('os.getcwd') as getcwd:
            getcwd.side_effect = FileNotFoundError('CWD is gone')
            options, _ = self.tool.parse_args(self.args + ['cat/pkg'])
            assert options.cwd == '/'

    def test_selected_keywords(self):
        for opt in ('-k', '--keywords'):
            options, _ = self.tool.parse_args(self.args + [opt, 'InvalidPN'])
            result_cls = next(v for k, v in objects.KEYWORDS.items() if k == 'InvalidPN')
            assert options.filtered_keywords == {result_cls}
            check = next(x for x in objects.CHECKS.values() if result_cls in x.known_results)
            assert options.enabled_checks == [check]

    def test_missing_scope(self, capsys):
        for opt in ('-s', '--scopes'):
            with pytest.raises(SystemExit) as excinfo:
                options, _ = self.tool.parse_args(self.args + [opt])
            assert excinfo.value.code == 2
            out, err = capsys.readouterr()
            err = err.strip().split('\n')
            assert err[0] == (
                'pkgcheck scan: error: argument -s/--scopes: expected one argument')

    def test_no_active_checks(self, capsys):
        args = self.args + ['-c', 'UnusedInMastersCheck']
        with pytest.raises(SystemExit) as excinfo:
            options, _ = self.tool.parse_args(args)
        assert excinfo.value.code == 2
        out, err = capsys.readouterr()
        err = err.strip().split('\n')
        assert err[-1].startswith("pkgcheck scan: error: no matching checks available")

    def test_conflicting_scan_scopes(self, capsys, fakerepo):
        """Multiple targets can't specify different scopes."""
        with pytest.raises(SystemExit) as excinfo:
            self.tool.parse_args(self.args + [fakerepo, 'cat/pkg'])
        assert excinfo.value.code == 2
        out, err = capsys.readouterr()
        err = err.strip().split('\n')
        assert err[-1].startswith(
            "pkgcheck scan: error: targets specify multiple scan scope levels: package, repo")

    def test_collapsed_restrictions(self):
        """Multiple targets get collapsed into one restriction to run in parallel."""
        options, _ = self.tool.parse_args(self.args + ['cat/pkg1', 'cat/pkg2'])
        scope, restrict = list(options.restrictions)[0]
        assert scope is base.package_scope
        assert restrict.restrictions == (atom.atom('cat/pkg1'), atom.atom('cat/pkg2'))

    def test_eclass_target(self, fakerepo):
        os.makedirs(pjoin(fakerepo, 'eclass'))
        eclass_path = pjoin(fakerepo, 'eclass', 'foo.eclass')
        touch(eclass_path)
        options, _ = self.tool.parse_args(self.args + [eclass_path])
        scope, restrict = list(options.restrictions)[0]
        assert scope == base.eclass_scope

    def test_profiles_target(self, fakerepo):
        profiles_path = pjoin(fakerepo, 'profiles')
        options, _ = self.tool.parse_args(self.args + [profiles_path])
        assert list(options.restrictions) == [(base.profiles_scope, packages.AlwaysTrue)]

    def test_argparse_error(self, capsys):
        """Argparse errors are used for error mesages under normal operation."""
        action = argparse.Action(['--foo'], 'foo')
        with patch('pkgcheck.addons.ProfileAddon.check_args') as check_args:
            check_args.side_effect = argparse.ArgumentError(action, 'invalid arg')
            with pytest.raises(SystemExit) as excinfo:
                self.tool.parse_args(self.args + ['cat/pkg'])
            assert excinfo.value.code == 2
            out, err = capsys.readouterr()
            err = err.strip().split('\n')
            assert err[-1].startswith('pkgcheck scan: error: argument --foo: invalid arg')

    def test_argparse_error_debug(self, capsys):
        """Argparse errors are raised when parsing args under debug mode."""
        action = argparse.Action(['--foo'], 'foo')
        with patch('pkgcheck.addons.ProfileAddon.check_args') as check_args:
            check_args.side_effect = argparse.ArgumentError(action, 'invalid arg')
            with pytest.raises(argparse.ArgumentError):
                self.tool.parse_args(self.args + ['--debug', 'cat/pkg'])

    def test_exit_keywords(self):
        # no exit arg
        options, _ = self.tool.parse_args(self.args)
        assert options.exit_keywords == ()

        # default error keywords
        options, _ = self.tool.parse_args(self.args + ['--exit'])
        assert options.exit_keywords == frozenset(objects.KEYWORDS.error.values())


class TestPkgcheckScan:

    script = partial(run, project)

    testdir = os.path.dirname(os.path.dirname(__file__))
    repos_data = pjoin(testdir, 'data', 'repos')
    repos_dir = pjoin(testdir, 'repos')
    repos = tuple(sorted(os.listdir(repos_data)))

    _all_results = []
    for name, cls in sorted(objects.CHECKS.items()):
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

    def test_empty_repo(self, capsys, cache_dir):
        # no reports should be generated since the default repo is empty
        with patch('sys.argv', self.args):
            with pytest.raises(SystemExit) as excinfo:
                self.script()
            assert excinfo.value.code == 0
            out, err = capsys.readouterr()
            assert out == err == ''

    @pytest.mark.parametrize(
        'action, module',
        (('init', 'Process'), ('queue', 'UnversionedSource'), ('run', 'CheckRunner.run')))
    def test_pipeline_exceptions(self, action, module, capsys, cache_dir):
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
    def test_scan_repo(self, repo, capsysbinary, cache_dir, tmp_path, verbosity=0):
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
    def test_scan_repo_verbose(self, repo, capsysbinary, cache_dir, tmp_path):
        """Scan a target repo in verbose mode, saving results for verfication."""
        return self.test_scan_repo(repo, capsysbinary, cache_dir, tmp_path, verbosity=1)

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
    def test_scan_verify(self, repo, capsys, cache_dir, tmp_path):
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
    def test_scan_fix(self, check, result, capsys, cache_dir, tmp_path):
        """Apply fixes to pkgs, verifying the related results are fixed."""
        check_name = check.__name__
        keyword = result.__name__
        tested = False
        for repo in os.listdir(self.repos_data):
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
