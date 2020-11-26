import random

import pytest
from pkgcheck import argparsers, base, checks, objects
from pkgcheck.caches import CachedAddon
from snakeoil.cli import arghparse


class TestConfigArg:

    @pytest.fixture(autouse=True)
    def _create_argparser(self):
        self.parser = arghparse.ArgumentParser()
        self.parser.add_argument('--config', action=argparsers.ConfigArg)

    def test_none(self):
        args = self.parser.parse_args([])
        assert args.config is None

    def test_enabled(self):
        for arg in ('config_file', '/path/to/config/file'):
            args = self.parser.parse_args(['--config', arg])
            assert args.config == arg

    def test_disabled(self):
        for arg in ('False', 'false', 'No', 'no', 'N', 'n'):
            args = self.parser.parse_args(['--config', arg])
            assert args.config is False


class TestCacheNegations:

    @pytest.fixture(autouse=True)
    def _create_argparser(self):
        self.parser = arghparse.ArgumentParser()
        self.parser.add_argument('--cache', action=argparsers.CacheNegations)
        self.caches = [x.type for x in CachedAddon.caches.values()]

    def test_no_arg(self):
        args = self.parser.parse_args([])
        assert args.cache is None

    def test_unknown(self, capsys):
        with pytest.raises(SystemExit) as excinfo:
            self.parser.parse_args(['--cache', 'foo'])
        out, err = capsys.readouterr()
        assert not out
        assert "unknown cache type: 'foo'" in err
        assert excinfo.value.code == 2

    def test_all(self):
        for arg in ('True', 'true', 'Yes', 'yes', 'Y', 'y'):
            args = self.parser.parse_args(['--cache', arg])
            for k, v in args.cache.items():
                assert v is True

    def test_none(self):
        for arg in ('False', 'false', 'No', 'no', 'N', 'n'):
            args = self.parser.parse_args(['--cache', arg])
            for k, v in args.cache.items():
                assert v is False

    def test_enabled(self):
        cache = self.caches[random.randrange(len(self.caches))]
        args = self.parser.parse_args(['--cache', cache])
        for k, v in args.cache.items():
            if k == cache:
                assert v is True
            else:
                assert v is False

    def test_disabled(self):
        cache = self.caches[random.randrange(len(self.caches))]
        args = self.parser.parse_args([f'--cache=-{cache}'])
        for k, v in args.cache.items():
            if k == cache:
                assert v is False
            else:
                assert v is True


class TestScopeArgs:

    @pytest.fixture(autouse=True)
    def _setup(self, tool, tmp_path):
        self.tool = tool
        self.cache_dir = str(tmp_path)
        self.args = ['scan', '--cache-dir', self.cache_dir]

    def test_unknown_scope(self, capsys):
        for opt in ('-s', '--scopes'):
            with pytest.raises(SystemExit) as excinfo:
                options, _ = self.tool.parse_args(self.args + [opt, 'foo'])
            assert excinfo.value.code == 2
            out, err = capsys.readouterr()
            err = err.strip().split('\n')
            assert "unknown scope: 'foo'" in err[-1]

    def test_missing_scope(self, capsys):
        for opt in ('-s', '--scopes'):
            with pytest.raises(SystemExit) as excinfo:
                options, _ = self.tool.parse_args(self.args + [opt])
            assert excinfo.value.code == 2
            out, err = capsys.readouterr()
            err = err.strip().split('\n')
            assert err[0] == (
                'pkgcheck scan: error: argument -s/--scopes: expected one argument')

    def test_disabled(self):
        args, _ = self.tool.parse_args(self.args + ['--scopes=-eclass'])
        assert args.selected_scopes == frozenset()

    def test_enabled(self):
        args, _ = self.tool.parse_args(self.args + ['--scopes', 'repo'])
        assert args.selected_scopes == frozenset([base.scopes['repo']])


class TestCheckArgs:

    @pytest.fixture(autouse=True)
    def _setup(self, tool, tmp_path):
        self.tool = tool
        self.cache_dir = str(tmp_path)
        self.args = ['scan', '--cache-dir', self.cache_dir]

    def test_unknown_check(self, capsys):
        for opt in ('-c', '--checks'):
            with pytest.raises(SystemExit) as excinfo:
                options, _ = self.tool.parse_args(self.args + [opt, 'foo'])
            assert excinfo.value.code == 2
            out, err = capsys.readouterr()
            err = err.strip().split('\n')
            assert "unknown check: 'foo'" in err[-1]

    def test_missing_check(self, capsys):
        for opt in ('-c', '--checks'):
            with pytest.raises(SystemExit) as excinfo:
                options, _ = self.tool.parse_args(self.args + [opt])
            assert excinfo.value.code == 2
            out, err = capsys.readouterr()
            err = err.strip().split('\n')
            assert err[0] == (
                'pkgcheck scan: error: argument -c/--checks: expected one argument')

    def test_enabled(self):
        for opt in ('-c', '--checks'):
            args, _ = self.tool.parse_args(self.args + [opt, 'UnusedLicensesCheck'])
            assert args.selected_checks == frozenset(['UnusedLicensesCheck'])

    def test_disabled(self):
        for opt in ('-c', '--checks'):
            check = list(objects.CHECKS)[random.randrange(len(objects.CHECKS))]
            args, _ = self.tool.parse_args(self.args + [f'{opt}=-{check}'])
            assert args.selected_checks == frozenset()

    def test_additive(self):
        for opt in ('-c', '--checks'):
            args, _ = self.tool.parse_args(self.args)
            assert issubclass(checks.perl.PerlCheck, checks.OptionalCheck)
            assert checks.perl.PerlCheck not in set(args.enabled_checks)
            args, _ = self.tool.parse_args(self.args + [f'{opt}=+PerlCheck'])
            assert checks.perl.PerlCheck in set(args.enabled_checks)
            assert args.selected_checks == frozenset(['PerlCheck'])

    def test_aliases(self):
        for opt in ('-c', '--checks'):
            # net
            args, _ = self.tool.parse_args(self.args + [opt, 'net'])
            network_checks = [
                c for c, v in objects.CHECKS.items() if issubclass(v, checks.NetworkCheck)]
            assert args.selected_checks == frozenset(network_checks)

            # all
            args, _ = self.tool.parse_args(self.args + [opt, 'all'])
            assert args.selected_checks == frozenset(objects.CHECKS)


class TestKeywordArgs:

    @pytest.fixture(autouse=True)
    def _setup(self, tool, tmp_path):
        self.tool = tool
        self.cache_dir = str(tmp_path)
        self.args = ['scan', '--cache-dir', self.cache_dir]

    def test_unknown_keyword(self, capsys):
        for opt in ('-k', '--keywords'):
            with pytest.raises(SystemExit) as excinfo:
                options, _ = self.tool.parse_args(self.args + [opt, 'foo'])
            assert excinfo.value.code == 2
            out, err = capsys.readouterr()
            err = err.strip().split('\n')
            assert "unknown keyword: 'foo'" in err[-1]

    def test_missing_keyword(self, capsys):
        for opt in ('-k', '--keywords'):
            with pytest.raises(SystemExit) as excinfo:
                options, _ = self.tool.parse_args(self.args + [opt])
            assert excinfo.value.code == 2
            out, err = capsys.readouterr()
            err = err.strip().split('\n')
            assert err[0] == (
                'pkgcheck scan: error: argument -k/--keywords: expected one argument')

    def test_enabled(self):
        args, _ = self.tool.parse_args(self.args + ['--keywords', 'UnusedLicenses'])
        assert args.selected_keywords == frozenset(['UnusedLicenses'])

    def test_disabled(self):
        keyword = list(objects.KEYWORDS)[random.randrange(len(objects.KEYWORDS))]
        args, _ = self.tool.parse_args(self.args + [f'--keywords=-{keyword}'])
        assert args.selected_keywords == frozenset()

    def test_aliases(self):
        for alias in ('error', 'warning', 'info'):
            args, _ = self.tool.parse_args(self.args + ['--keywords', alias])
            alias_keywords = list(getattr(objects.KEYWORDS, alias))
            assert args.selected_keywords == frozenset(alias_keywords)


class TestExitArgs:

    @pytest.fixture(autouse=True)
    def _setup(self, tool, tmp_path):
        self.tool = tool
        self.cache_dir = str(tmp_path)
        self.args = ['scan', '--cache-dir', self.cache_dir]

    def test_unknown(self, capsys):
        with pytest.raises(SystemExit) as excinfo:
            self.tool.parse_args(self.args + ['--exit', 'foo'])
        out, err = capsys.readouterr()
        assert not out
        assert "unknown keyword: 'foo'" in err
        assert excinfo.value.code == 2

    def test_none(self):
        args, _ = self.tool.parse_args(self.args)
        assert args.exit_keywords == ()

    def test_default(self):
        args, _ = self.tool.parse_args(self.args + ['--exit'])
        assert args.exit_keywords == frozenset(objects.KEYWORDS.error.values())

    def test_enabled(self):
        keyword = list(objects.KEYWORDS)[random.randrange(len(objects.KEYWORDS))]
        cls = objects.KEYWORDS[keyword]
        args, _ = self.tool.parse_args(self.args + ['--exit', keyword])
        assert args.exit_keywords == frozenset([cls])

    def test_disabled(self):
        keyword = list(objects.KEYWORDS)[random.randrange(len(objects.KEYWORDS))]
        cls = objects.KEYWORDS[keyword]
        args, _ = self.tool.parse_args(self.args + [f'--exit=-{keyword}'])
        assert args.exit_keywords == frozenset(objects.KEYWORDS.error.values()) - frozenset([cls])

    def test_aliases(self):
        for alias in ('error', 'warning', 'info'):
            args, _ = self.tool.parse_args(self.args + [f'--exit={alias}'])
            assert args.exit_keywords == frozenset(getattr(objects.KEYWORDS, alias).values())
