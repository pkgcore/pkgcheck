import random

import pytest
from pkgcheck import argparsers, base, objects
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
    def _create_argparser(self):
        self.parser = arghparse.ArgumentParser()
        self.parser.add_argument('--scopes', action=argparsers.ScopeArgs)

    def test_no_arg(self):
        args = self.parser.parse_args([])
        assert args.scopes is None

    def test_unknown(self, capsys):
        with pytest.raises(SystemExit) as excinfo:
            self.parser.parse_args(['--scopes', 'foo'])
        out, err = capsys.readouterr()
        assert not out
        assert "unknown scope: 'foo'" in err
        assert excinfo.value.code == 2

    def test_disabled(self):
        scope = list(base.scopes)[random.randrange(len(base.scopes))]
        args = self.parser.parse_args([f'--scopes=-{scope}'])
        assert args.scopes == ({base.scopes[scope]}, set())

    def test_enabled(self):
        scope = list(base.scopes)[random.randrange(len(base.scopes))]
        args = self.parser.parse_args(['--scopes', scope])
        assert args.scopes == (set(), {base.scopes[scope]})


class TestKeywordArgs:

    @pytest.fixture(autouse=True)
    def _create_argparser(self):
        self.parser = arghparse.ArgumentParser()
        self.parser.add_argument('--keywords', action=argparsers.KeywordArgs)

    def test_no_arg(self):
        args = self.parser.parse_args([])
        assert args.keywords is None

    def test_unknown(self, capsys):
        with pytest.raises(SystemExit) as excinfo:
            self.parser.parse_args(['--keywords', 'foo'])
        out, err = capsys.readouterr()
        assert not out
        assert "unknown keyword: 'foo'" in err
        assert excinfo.value.code == 2

    def test_enabled(self):
        keyword = list(objects.KEYWORDS)[random.randrange(len(objects.KEYWORDS))]
        args = self.parser.parse_args(['--keywords', keyword])
        assert args.keywords == ([], [keyword])

    def test_disabled(self):
        keyword = list(objects.KEYWORDS)[random.randrange(len(objects.KEYWORDS))]
        args = self.parser.parse_args([f'--keywords=-{keyword}'])
        assert args.keywords == ([keyword], [])


class TestCheckArgs:

    @pytest.fixture(autouse=True)
    def _create_argparser(self):
        self.parser = arghparse.ArgumentParser()
        self.parser.add_argument('--checks', action=argparsers.CheckArgs)

    def test_no_arg(self):
        args = self.parser.parse_args([])
        assert args.checks is None

    def test_unknown(self, capsys):
        with pytest.raises(SystemExit) as excinfo:
            self.parser.parse_args(['--checks', 'foo'])
        out, err = capsys.readouterr()
        assert not out
        assert "unknown check: 'foo'" in err
        assert excinfo.value.code == 2

    def test_enabled(self):
        check = list(objects.CHECKS)[random.randrange(len(objects.CHECKS))]
        args = self.parser.parse_args(['--checks', check])
        assert args.checks == ([], [check])

    def test_disabled(self):
        check = list(objects.CHECKS)[random.randrange(len(objects.CHECKS))]
        args = self.parser.parse_args([f'--checks=-{check}'])
        assert args.checks == ([check], [])


class TestExitArgs:

    @pytest.fixture(autouse=True)
    def _create_argparser(self):
        self.parser = arghparse.ArgumentParser()
        self.parser.add_argument('--exit', nargs='?', action=argparsers.ExitArgs)

    def test_unknown(self, capsys):
        with pytest.raises(SystemExit) as excinfo:
            self.parser.parse_args(['--exit', 'foo'])
        out, err = capsys.readouterr()
        assert not out
        assert "unknown keyword: 'foo'" in err
        assert excinfo.value.code == 2

    def test_none(self):
        args = self.parser.parse_args([])
        assert args.exit is None

    def test_default(self):
        args = self.parser.parse_args(['--exit'])
        assert args.exit == frozenset(objects.KEYWORDS.error.values())

    def test_enabled(self):
        keyword = list(objects.KEYWORDS)[random.randrange(len(objects.KEYWORDS))]
        cls = objects.KEYWORDS[keyword]
        args = self.parser.parse_args(['--exit', keyword])
        assert args.exit == frozenset([cls])

    def test_disabled(self):
        keyword = list(objects.KEYWORDS)[random.randrange(len(objects.KEYWORDS))]
        cls = objects.KEYWORDS[keyword]
        args = self.parser.parse_args([f'--exit=-{keyword}'])
        assert args.exit == frozenset(objects.KEYWORDS.error.values()) - frozenset([cls])
