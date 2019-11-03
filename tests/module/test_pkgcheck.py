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
from pkgcore import const as pkgcore_const
from pkgcore.ebuild import atom, restricts
from pkgcore.ebuild.repository import UnconfiguredTree
from pkgcore.restrictions import packages
from snakeoil.contexts import chdir
from snakeoil.fileutils import touch
from snakeoil.formatters import PlainTextFormatter
from snakeoil.osutils import pjoin

from pkgcheck import __title__ as project
from pkgcheck import base, checks, const, reporters
from pkgcheck.checks.profiles import ProfileWarning
from pkgcheck.scripts import pkgcheck, run


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
    def _setup(self, tool):
        self.tool = tool
        self.args = ['scan']

    def test_skipped_checks(self):
        options, _func = self.tool.parse_args(self.args)
        assert options.enabled_checks
        # some checks should always be skipped by default
        assert set(options.enabled_checks) != set(const.CHECKS.values())

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
        assert list(options.restrictions) == [(base.package_scope, atom.atom('dev-util/foo'))]

    def test_stdin_targets(self):
        with patch('sys.stdin', StringIO('dev-util/foo')):
            options, _func = self.tool.parse_args(self.args + ['-'])
            assert list(options.restrictions) == [(base.package_scope, atom.atom('dev-util/foo'))]

    def test_invalid_targets(self, capsys):
        with pytest.raises(SystemExit) as excinfo:
            options, _func = self.tool.parse_args(self.args + ['dev-util/f$o'])
            # force target parsing
            list(options.restrictions)
        assert excinfo.value.code == 2
        out, err = capsys.readouterr()
        err = err.strip()
        assert err == "pkgcheck scan: error: invalid package atom: 'dev-util/f$o'"

    def test_selected_targets(self, fakerepo):
        # selected repo
        options, _func = self.tool.parse_args(self.args + ['-r', 'stubrepo'])
        assert options.target_repo.repo_id == 'stubrepo'
        assert options.restrictions == [(base.repository_scope, packages.AlwaysTrue)]

        # dir path
        options, _func = self.tool.parse_args(self.args + [fakerepo])
        assert options.target_repo.repo_id == 'fakerepo'
        assert options.restrictions == [(base.repository_scope, packages.AlwaysTrue)]

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
            assert list(options.restrictions) == [(base.repository_scope, packages.AlwaysTrue)]

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
            assert err[-1].startswith("pkgcheck scan: error: unknown scope: 'foo'")

    def test_unknown_check(self, capsys):
        for opt in ('-c', '--checks'):
            with pytest.raises(SystemExit) as excinfo:
                options, _func = self.tool.parse_args(self.args + [opt, 'foo'])
            assert excinfo.value.code == 2
            out, err = capsys.readouterr()
            err = err.strip().split('\n')
            assert err[-1].startswith("pkgcheck scan: error: unknown check: 'foo'")

    def test_unknown_keyword(self, capsys):
        for opt in ('-k', '--keywords'):
            with pytest.raises(SystemExit) as excinfo:
                options, _func = self.tool.parse_args(self.args + [opt, 'foo'])
            assert excinfo.value.code == 2
            out, err = capsys.readouterr()
            err = err.strip().split('\n')
            assert err[-1].startswith("pkgcheck scan: error: unknown keyword: 'foo'")

    def test_selected_keywords(self):
        for opt in ('-k', '--keywords'):
            options, _func = self.tool.parse_args(self.args + [opt, 'InvalidPN'])
            result_cls = next(v for k, v in const.KEYWORDS.items() if k == 'InvalidPN')
            assert options.enabled_keywords == [result_cls]
            check = next(x for x in const.CHECKS.values() if result_cls in x.known_results)
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
            assert err[-1].startswith("pkgcheck scan: error: no active checks")


class TestPkgcheck(object):

    script = partial(run, project)

    def test_version(self, capsys):
        with patch('sys.argv', [project, '--version']):
            with pytest.raises(SystemExit) as excinfo:
                self.script()
            assert excinfo.value.code == 0
            out, err = capsys.readouterr()
            assert out.startswith(project)


class TestPkgcheckScan(object):

    script = partial(run, project)
    _results = defaultdict(set)
    _checks_run = set()

    @pytest.fixture(autouse=True)
    def _setup(self, testconfig):
        self.args = [project, '--config', testconfig, 'scan']
        self.testdir = os.path.dirname(os.path.dirname(__file__))

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
                patch('pkgcheck.base.CACHE_DIR', cache_dir):
            with pytest.raises(SystemExit) as excinfo:
                self.script()
            assert excinfo.value.code == 0
            out, err = capsys.readouterr()
            assert out == err == ''

    results = []
    for name, cls in sorted(const.CHECKS.items()):
        for result in sorted(cls.known_results, key=attrgetter('__name__')):
            results.append((cls, result))

    def test_pkgcheck_test_repos(self):
        """Make sure the test repos are up to date check/result naming wise."""
        # grab custom targets
        custom_targets = set()
        for repo in os.listdir(pjoin(self.testdir, 'data')):
            for root, _dirs, files in os.walk(pjoin(self.testdir, 'data', repo)):
                for f in files:
                    if f == 'target':
                        with open(pjoin(root, f)) as target:
                            custom_targets.add(target.read().strip())

        # all pkgs that aren't custom targets or stubs must be check/keyword
        for repo_dir in os.listdir(pjoin(self.testdir, 'repos')):
            repo = UnconfiguredTree(pjoin(self.testdir, 'repos', repo_dir))

            # determine pkg stubs added to the repo
            stubs = set()
            try:
                with open(pjoin(repo.location, 'metadata', 'stubs')) as f:
                    stubs.update(x.rstrip() for x in f)
            except FileNotFoundError:
                pass

            allowed = custom_targets | stubs
            results = {(check.__name__, result.__name__) for check, result in self.results}
            for cat, pkgs in sorted(repo.packages.items()):
                if cat.startswith('stub'):
                    continue
                for pkg in sorted(pkgs):
                    if pkg.startswith('stub'):
                        continue
                    if f'{cat}/{pkg}' not in allowed:
                        assert (cat, pkg) in results

    def test_pkgcheck_test_data(self):
        """Make sure the test data is up to date check/result naming wise."""
        for repo in os.listdir(pjoin(self.testdir, 'data')):
            for check in os.listdir(pjoin(self.testdir, f'data/{repo}')):
                assert check in const.CHECKS
                for keyword in os.listdir(pjoin(self.testdir, f'data/{repo}/{check}')):
                    assert keyword in const.KEYWORDS

    @pytest.mark.parametrize('check, result', results)
    def test_pkgcheck_scan(self, check, result, capsys, cache_dir, tmp_path):
        """Run pkgcheck against test pkgs in bundled repo, verifying result output."""
        tested = False
        check_name = check.__name__
        keyword = result.__name__
        for repo in os.listdir(pjoin(self.testdir, 'data')):
            for verbosity, file in ((0, 'expected'), (1, 'expected-verbose')):
                expected_path = pjoin(self.testdir, f'data/{repo}/{check_name}/{keyword}/{file}')
                if not os.path.exists(expected_path):
                    continue

                repo_dir = pjoin(self.testdir, 'repos', repo)

                # create issue related to keyword as required
                trigger = pjoin(self.testdir, f'data/{repo}/{check_name}/{keyword}/trigger.sh')
                if os.path.exists(trigger):
                    triggered_repo = str(tmp_path / f'triggered-{repo}')
                    shutil.copytree(repo_dir, triggered_repo)
                    self._script(trigger, triggered_repo)
                    repo_dir = triggered_repo

                args = (['-v'] * verbosity) + ['-r', repo_dir]

                # determine what test target to use
                try:
                    target = open(pjoin(self.testdir, f'data/{repo}/{check_name}/{keyword}/target'))
                    args.extend(shlex.split(target.read()))
                except FileNotFoundError:
                    if base.repository_scope in (result.scope, check.scope):
                        args.extend(['-k', keyword])
                    elif result.scope == base.category_scope:
                        args.append(f'{keyword}/*')
                    elif result.scope in (base.package_scope, base.version_scope):
                        args.append(f'{check_name}/{keyword}')
                    else:
                        pytest.fail(f'{keyword} result for {check_name} check has unknown scope')

                with open(expected_path) as f:
                    expected = f.read()
                    # JsonStream reporter, cache results to compare against repo run
                    with patch('sys.argv', self.args + ['-R', 'JsonStream'] + args), \
                            patch('pkgcheck.base.CACHE_DIR', cache_dir):
                        with pytest.raises(SystemExit) as excinfo:
                            self.script()
                        out, err = capsys.readouterr()
                        if not verbosity:
                            assert not err
                        assert excinfo.value.code == 0
                        if not expected:
                            assert not out
                        else:
                            results = []
                            for line in out.rstrip('\n').split('\n'):
                                deserialized_result = reporters.JsonStream.from_json(line)
                                assert deserialized_result.__class__.__name__ == keyword
                                results.append(deserialized_result)
                                if not verbosity:
                                    self._results[repo].add(deserialized_result)
                            # compare rendered fancy out to expected
                            assert self._render_results(
                                sorted(results), verbosity=verbosity) == expected
                tested = True
                self._checks_run.add(check_name)

        if not tested:
            pytest.skip('expected test data not available')

    def _render_results(self, results, **kwargs):
        """Render a given set of result objects into their related string form."""
        with tempfile.TemporaryFile() as f:
            with reporters.FancyReporter(out=PlainTextFormatter(f), **kwargs) as reporter:
                for result in results:
                    reporter.report(result)
            f.seek(0)
            output = f.read().decode()
            return output

    def test_pkgcheck_scan_repos(self, capsys, cache_dir, tmp_path):
        """Verify full repo scans don't return any extra, unknown results."""
        # TODO: replace with matching against expected full scan dump once
        # sorting is implemented
        if not self._results:
            pytest.skip('test_pkgcheck_scan() must be run before this to populate results')
        else:
            for repo in os.listdir(pjoin(self.testdir, 'data')):
                unknown_results = []
                repo_dir = pjoin(self.testdir, 'repos', repo)

                # create issues related to keyword as required
                triggers = []
                for root, _dirs, files in os.walk(pjoin(self.testdir, 'data', repo)):
                    for f in files:
                        if f == 'trigger.sh':
                            triggers.append(pjoin(root, f))
                if triggers:
                    triggered_repo = str(tmp_path / f'triggered-{repo}')
                    shutil.copytree(repo_dir, triggered_repo)
                    for trigger in triggers:
                        self._script(trigger, triggered_repo)
                    repo_dir = triggered_repo

                args = ['-r', repo_dir, '-c', ','.join(self._checks_run)]
                with patch('sys.argv', self.args + ['-R', 'JsonStream'] + args), \
                        patch('pkgcheck.base.CACHE_DIR', cache_dir):
                    with pytest.raises(SystemExit) as excinfo:
                        self.script()
                    out, err = capsys.readouterr()
                    assert out, f'{repo} repo failed, no results'
                    assert excinfo.value.code == 0
                    for line in out.rstrip('\n').split('\n'):
                        result = reporters.JsonStream.from_json(line)
                        # ignore results generated from stubs
                        stubs = (getattr(result, x, '') for x in ('category', 'package'))
                        if any(x.startswith('stub') for x in stubs):
                            continue
                        try:
                            self._results[repo].remove(result)
                        except KeyError:
                            unknown_results.append(result)

                if self._results[repo]:
                    output = self._render_results(self._results[repo])
                    pytest.fail(f'{repo} repo missing results:\n{output}')
                if unknown_results:
                    output = self._render_results(unknown_results)
                    pytest.fail(f'{repo} repo has unknown results:\n{output}')

    @pytest.mark.parametrize('check, result', results)
    def test_pkgcheck_scan_fix(self, check, result, capsys, cache_dir, tmp_path):
        """Apply fixes to pkgs, verifying the related results are fixed."""
        check_name = check.__name__
        keyword = result.__name__
        tested = False
        for repo in os.listdir(pjoin(self.testdir, 'data')):
            keyword_dir = pjoin(self.testdir, f'data/{repo}/{check_name}/{keyword}')
            if os.path.exists(pjoin(keyword_dir, 'fix.patch')):
                fix = pjoin(keyword_dir, 'fix.patch')
                func = self._patch
            elif os.path.exists(pjoin(keyword_dir, 'fix.sh')):
                fix = pjoin(keyword_dir, 'fix.sh')
                func = self._script
            else:
                continue

            # apply a fix if one exists and make sure the related result doesn't appear
            repo_dir = pjoin(self.testdir, 'repos', repo)
            fixed_repo = str(tmp_path / f'fixed-{repo}')
            shutil.copytree(repo_dir, fixed_repo)
            func(fix, fixed_repo)

            args = ['-r', fixed_repo]
            if base.repository_scope in (result.scope, check.scope):
                args.extend(['-k', keyword])
            elif result.scope == base.category_scope:
                args.append(f'{keyword}/*')
            elif result.scope in (base.package_scope, base.version_scope):
                args.append(f'{check_name}/{keyword}')
            else:
                pytest.fail(f'{keyword} result for {check_name} check has unknown scope')

            cmd = self.args + args
            with patch('sys.argv', cmd), \
                    patch('pkgcheck.base.CACHE_DIR', cache_dir):
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
            assert out == sorted(const.KEYWORDS.keys())
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
            assert out == sorted(const.KEYWORDS.keys())
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
            assert out == sorted(const.CHECKS.keys())
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
            assert out == list(base.scopes)
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
            assert out == sorted(const.REPORTERS.keys())
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
        for reporter_cls in (reporters.BinaryPickleStream, reporters.JsonStream):
            with tempfile.NamedTemporaryFile() as f:
                out = PlainTextFormatter(f)
                with reporter_cls(out) as reporter:
                    reporter.report(result)
                with patch('sys.argv', self.args + ['-R', 'StrReporter', f.name]):
                    with pytest.raises(SystemExit) as excinfo:
                        self.script()
                    out, err = capsys.readouterr()
                    assert not err
                    assert out == 'profile warning: foo\n'
