import random

import pytest
from pkgcheck import argparsers, objects, results
from snakeoil.cli import arghparse


class TestConfigArg:

    @pytest.fixture(autouse=True)
    def _create_argparser(self):
        self.parser = arghparse.ArgumentParser()
        self.parser.add_argument('--config', action=argparsers.ConfigArg)

    def test_enabled(self):
        for arg in ('config_file', '/path/to/config/file'):
            args = self.parser.parse_args(['--config', arg])
            assert args.config == arg

    def test_disabled(self):
        for arg in ('False', 'false', 'No', 'no', 'N', 'n'):
            args = self.parser.parse_args(['--config', arg])
            assert args.config is False


class TestExitArgs:

    # set of all result error classes
    errors = frozenset(
        v for k, v in objects.KEYWORDS.items() if issubclass(v, results.Error))

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
        assert args.exit == self.errors

    def test_enabled(self):
        keyword = list(objects.KEYWORDS)[random.randrange(len(objects.KEYWORDS))]
        cls = objects.KEYWORDS[keyword]
        args = self.parser.parse_args(['--exit', keyword])
        assert args.exit == frozenset([cls])

    def test_disabled(self):
        keyword = list(objects.KEYWORDS)[random.randrange(len(objects.KEYWORDS))]
        cls = objects.KEYWORDS[keyword]
        args = self.parser.parse_args([f'--exit=-{keyword}'])
        assert args.exit == self.errors - frozenset([cls])
