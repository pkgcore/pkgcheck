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
from pkgcheck import base, objects, reporters
from pkgcheck import checks as checks_mod
from pkgcheck.scripts import run
from pkgcore import const as pkgcore_const
from pkgcore.ebuild import atom, restricts
from pkgcore.ebuild.repository import UnconfiguredTree
from pkgcore.restrictions import packages
from snakeoil.contexts import chdir
from snakeoil.fileutils import touch
from snakeoil.formatters import PlainTextFormatter
from snakeoil.osutils import pjoin


class TestPkgcheckScanParseArgs:

    @pytest.fixture(autouse=True)
    def _setup(self, tool):
        self.tool = tool
        self.args = ['scan']

    def test_skipped_checks(self):
        options, _func = self.tool.parse_args(self.args)
        assert options.enabled_checks
        # some checks should always be skipped by default
        assert set(options.enabled_checks) != set(objects.CHECKS.values())

    def test_enabled_check(self):
        options, _func = self.tool.parse_args(self.args + ['-c', 'PkgDirCheck'])
        assert options.enabled_checks == [checks_mod.pkgdir.PkgDirCheck]

    def test_disabled_check(self):
        options, _func = self.tool.parse_args(self.args)
        assert checks_mod.pkgdir.PkgDirCheck in options.enabled_checks
        options, _func = self.tool.parse_args(self.args + ['-c=-PkgDirCheck'])
        assert options.enabled_checks
        assert checks_mod.pkgdir.PkgDirCheck not in options.enabled_checks

    def test_targets(self):
        options, _func = self.tool.parse_args(self.args + ['dev-util/foo'])
        assert list(options.restrictions) == [(base.package_scope, atom.atom('dev-util/foo'))]

    def test_stdin_targets(self):
        with patch('sys.stdin', StringIO('dev-util/foo')):
            options, _func = self.tool.parse_args(self.args + ['-'])
            assert list(options.restrictions) == [(base.package_scope, atom.atom('dev-util/foo'))]

    def test_invalid_targets(self, capsys):
        with pytest.raises(SystemExit) as excinfo:
            options, _func = self.tool.parse_args(self.args + ['dev-util/f$o'])
        assert excinfo.value.code == 2
        out, err = capsys.readouterr()
        err = err.strip()
        assert err == "pkgcheck scan: error: invalid package atom: 'dev-util/f$o'"

    def test_selected_targets(self, fakerepo):
        # selected repo
        options, _func = self.tool.parse_args(self.args + ['-r', 'stubrepo'])
        assert options.target_repo.repo_id == 'stubrepo'
        assert list(options.restrictions) == [(base.repo_scope, packages.AlwaysTrue)]

        # dir path
        options, _func = self.tool.parse_args(self.args + [fakerepo])
        assert options.target_repo.repo_id == 'fakerepo'
        assert list(options.restrictions) == [(base.repo_scope, packages.AlwaysTrue)]

        # file path
        os.makedirs(pjoin(fakerepo, 'dev-util', 'foo'))
        ebuild_path = pjoin(fakerepo, 'dev-util', 'foo', 'foo-0.ebuild')
        touch(ebuild_path)
        options, _func = self.tool.parse_args(self.args + [ebuild_path])
        restrictions = [
            restricts.CategoryDep('dev-util'),
            restricts.PackageDep('foo'),
            restricts.VersionMatch('=', '0'),
        ]
        assert list(options.restrictions) == [(base.version_scope, packages.AndRestriction(*restrictions))]
        assert options.target_repo.repo_id == 'fakerepo'

        # cwd path in unconfigured repo
        with chdir(pjoin(fakerepo, 'dev-util', 'foo')):
            options, _func = self.tool.parse_args(self.args)
            assert options.target_repo.repo_id == 'fakerepo'
            restrictions = [
                restricts.CategoryDep('dev-util'),
                restricts.PackageDep('foo'),
            ]
            assert list(options.restrictions) == [(base.package_scope, packages.AndRestriction(*restrictions))]

        # cwd path in configured repo
        stubrepo = pjoin(pkgcore_const.DATA_PATH, 'stubrepo')
        with chdir(stubrepo):
            options, _func = self.tool.parse_args(self.args)
            assert options.target_repo.repo_id == 'stubrepo'
            assert list(options.restrictions) == [(base.repo_scope, packages.AlwaysTrue)]

    def test_unknown_repo(self, capsys):
        for opt in ('-r', '--repo'):
            with pytest.raises(SystemExit) as excinfo:
                options, _func = self.tool.parse_args(self.args + [opt, 'foo'])
            assert excinfo.value.code == 2
            out, err = capsys.readouterr()
            err = err.strip().split('\n')
            assert err[-1].startswith(
                "pkgcheck scan: error: argument -r/--repo: couldn't find repo 'foo'")

    def test_unknown_reporter(self, capsys):
        for opt in ('-R', '--reporter'):
            with pytest.raises(SystemExit) as excinfo:
                options, _func = self.tool.parse_args(self.args + [opt, 'foo'])
            assert excinfo.value.code == 2
            out, err = capsys.readouterr()
            err = err.strip().split('\n')
            assert err[-1].startswith(
                "pkgcheck scan: error: no reporter matches 'foo'")

    def test_unknown_scope(self, capsys):
        for opt in ('-s', '--scopes'):
            with pytest.raises(SystemExit) as excinfo:
                options, _func = self.tool.parse_args(self.args + [opt, 'foo'])
            assert excinfo.value.code == 2
            out, err = capsys.readouterr()
            err = err.strip().split('\n')
            assert "unknown scope: 'foo'" in err[-1]

    def test_unknown_check(self, capsys):
        for opt in ('-c', '--checks'):
            with pytest.raises(SystemExit) as excinfo:
                options, _func = self.tool.parse_args(self.args + [opt, 'foo'])
            assert excinfo.value.code == 2
            out, err = capsys.readouterr()
            err = err.strip().split('\n')
            assert "unknown check: 'foo'" in err[-1]

    def test_unknown_keyword(self, capsys):
        for opt in ('-k', '--keywords'):
            with pytest.raises(SystemExit) as excinfo:
                options, _func = self.tool.parse_args(self.args + [opt, 'foo'])
            assert excinfo.value.code == 2
            out, err = capsys.readouterr()
            err = err.strip().split('\n')
            assert "unknown keyword: 'foo'" in err[-1]

    def test_selected_keywords(self):
        for opt in ('-k', '--keywords'):
            options, _func = self.tool.parse_args(self.args + [opt, 'InvalidPN'])
            result_cls = next(v for k, v in objects.KEYWORDS.items() if k == 'InvalidPN')
            assert options.filtered_keywords == {result_cls}
            check = next(x for x in objects.CHECKS.values() if result_cls in x.known_results)
            assert options.enabled_checks == [check]

    def test_missing_scope(self, capsys):
        for opt in ('-s', '--scopes'):
            with pytest.raises(SystemExit) as excinfo:
                options, _func = self.tool.parse_args(self.args + [opt])
            assert excinfo.value.code == 2
            out, err = capsys.readouterr()
            err = err.strip().split('\n')
            assert err[0] == (
                'pkgcheck scan: error: argument -s/--scopes: expected one argument')

    def test_no_active_checks(self, capsys):
        args = self.args + ['-c', 'UnusedInMastersCheck']
        with pytest.raises(SystemExit) as excinfo:
            options, _func = self.tool.parse_args(args)
        assert excinfo.value.code == 2
        out, err = capsys.readouterr()
        err = err.strip().split('\n')
        assert err[-1].startswith("pkgcheck scan: error: no matching checks available")


class TestPkgcheckScan:

    script = partial(run, project)

    testdir = os.path.dirname(os.path.dirname(__file__))
    repos_data = pjoin(testdir, 'data', 'repos')
    repos_dir = pjoin(testdir, 'repos')
    repos = tuple(sorted(os.listdir(repos_data)))

    @pytest.fixture(autouse=True)
    def _setup(self, testconfig):
        self.args = [project, '--config', testconfig, 'scan', '--config', 'no']

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
        with patch('sys.argv', self.args), \
                patch('pkgcheck.const.USER_CACHE_DIR', cache_dir):
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
                patch('pkgcheck.const.USER_CACHE_DIR', cache_dir), \
                patch(f'pkgcheck.pipeline.{module}') as faked:
            faked.side_effect = Exception('foobar')
            with pytest.raises(SystemExit) as excinfo:
                self.script()
            assert excinfo.value.code == 1
            out, err = capsys.readouterr()
            assert out == ''
            assert err.splitlines()[-1] == 'Exception: foobar'

    @pytest.mark.parametrize('repo', repos)
    def test_pkgcheck_test_repo(self, repo):
        """Make sure the test repos are up to date check/result naming wise."""
        custom_targets = set()
        for root, _dirs, files in os.walk(pjoin(self.repos_data, repo)):
            for f in files:
                if f == 'target':
                    with open(pjoin(root, f)) as target:
                        custom_targets.add(target.read().strip())

        repo_obj = UnconfiguredTree(pjoin(self.repos_dir, repo))

        # determine pkg stubs added to the repo
        stubs = set()
        try:
            with open(pjoin(repo_obj.location, 'metadata', 'stubs')) as f:
                stubs.update(x.rstrip() for x in f)
        except FileNotFoundError:
            pass

        # all pkgs that aren't custom targets or stubs must be check/keyword
        allowed = custom_targets | stubs
        results = {(check.__name__, result.__name__) for check, result in self.results}
        for cat, pkgs in sorted(repo_obj.packages.items()):
            if cat.startswith('stub'):
                continue
            for pkg in sorted(pkgs):
                if pkg.startswith('stub'):
                    continue
                if f'{cat}/{pkg}' not in allowed:
                    if pkg in objects.KEYWORDS:
                        assert (cat, pkg) in results
                    else:
                        assert cat in objects.KEYWORDS

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
    _results = defaultdict(set)
    _verbose_results = defaultdict(set)

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

        with patch('sys.argv', self.args + ['-R', 'BinaryPickleStream'] + args), \
                patch('pkgcheck.const.USER_CACHE_DIR', cache_dir):
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
                    self._verbose_results[repo].add(result)
                else:
                    self._results[repo].add(result)

    @pytest.mark.parametrize('repo', repos)
    def test_scan_repo_verbose(self, repo, capsysbinary, cache_dir, tmp_path):
        """Scan a target repo in verbose mode, saving results for verfication."""
        return self.test_scan_repo(repo, capsysbinary, cache_dir, tmp_path, verbosity=1)

    _all_results = []
    for name, cls in sorted(objects.CHECKS.items()):
        for result in sorted(cls.known_results, key=attrgetter('__name__')):
            _all_results.append((cls, result))

    def _get_results(self, path):
        try:
            with open(pjoin(self.repos_data, path)) as f:
                return set(reporters.JsonStream.from_iter(f))
        except FileNotFoundError:
            return set()

    @pytest.mark.parametrize('check, result', _all_results)
    def test_scan_verify_result(self, check, result, capsys, cache_dir, tmp_path):
        """Run pkgcheck against test pkgs in bundled repo, verifying result output."""
        tested = False
        check_name = check.__name__
        keyword = result.__name__
        for repo in os.listdir(self.repos_data):
            try:
                if keyword not in self._checks[repo][check_name]:
                    continue
            except KeyError:
                continue

            # verify the expected results were seen during the repo scans
            expected_results = self._get_results(f'{repo}/{check_name}/{keyword}/expected.json')
            if not expected_results:
                continue
            assert expected_results, 'regular results must always exist'
            assert self._render_results(expected_results), 'failed rendering results'
            assert expected_results <= self._results[repo]
            self._results[repo] -= expected_results

            # when expected verbose results exist use them, otherwise fallback to using the regular ones
            expected_verbose_results = self._get_results(f'{repo}/{check_name}/{keyword}/expected-verbose.json')
            if expected_verbose_results:
                assert expected_verbose_results <= self._verbose_results[repo]
                assert self._render_results(expected_verbose_results), 'failed rendering verbose results'
                self._verbose_results[repo] -= expected_verbose_results
            else:
                assert expected_results <= self._verbose_results[repo]
                self._verbose_results[repo] -= expected_results

            tested = True

        if not tested:
            pytest.skip('expected test data not available')

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
    def test_scan_verify_repo(self, repo):
        """Verify repo scans didn't return any extra, unknown results."""
        if self._results[repo]:
            output = self._render_results(self._results[repo])
            pytest.fail(f'{repo} repo missing results:\n{output}')
        if self._verbose_results[repo]:
            output = self._render_results(self._verbose_results[repo])
            pytest.fail(f'{repo} repo missing verbose results:\n{output}')

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
            with patch('sys.argv', cmd), \
                    patch('pkgcheck.const.USER_CACHE_DIR', cache_dir):
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
