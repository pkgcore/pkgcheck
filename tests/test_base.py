from itertools import chain
from unittest.mock import patch

from pkgcheck.base import ProgressManager


class TestProgressManager:

    def test_no_output(self, capsys):
        # output disabled due to lower verbosity setting
        with patch('sys.stdout.isatty', return_value=True):
            with ProgressManager(verbosity=-1) as progress:
                for x in range(10):
                    progress(x)
        # output disabled due to non-tty output
        with patch('sys.stdout.isatty', return_value=False):
            with ProgressManager(verbosity=1) as progress:
                for x in range(10):
                    progress(x)
        out, err = capsys.readouterr()
        assert not out
        assert not err

    def test_output(self, capsys):
        with patch('sys.stdout.isatty', return_value=True):
            with ProgressManager(verbosity=0) as progress:
                for x in range(10):
                    progress(x)
        out, err = capsys.readouterr()
        assert not out
        assert not err.strip().split('\r') == list(range(10))

    def test_cached_output(self, capsys):
        with patch('sys.stdout.isatty', return_value=True):
            with ProgressManager(verbosity=0) as progress:
                data = list(range(10))
                for x in chain.from_iterable(zip(data, data)):
                    progress(x)
        out, err = capsys.readouterr()
        assert not out
        assert not err.strip().split('\r') == list(range(10))
