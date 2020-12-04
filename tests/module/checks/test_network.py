import glob
import importlib.util
import io
import os
import socket
import tempfile
import urllib.request
from functools import partial
from operator import attrgetter
from unittest.mock import patch

from pkgcheck import __title__ as project
from pkgcheck import objects, reporters
from pkgcheck.checks import NetworkCheck
from pkgcheck.checks.network import HomepageUrlCheck, FetchablesUrlCheck, DeadUrl
from pkgcheck.packages import RawCPV
from pkgcheck.scripts import run
import pytest
from snakeoil.formatters import PlainTextFormatter
from snakeoil.osutils import pjoin
# skip module tests if requests isn't available
requests = pytest.importorskip('requests')


class TestNetworkChecks:

    script = partial(run, project)
    testdir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    repos_data = pjoin(testdir, 'data', 'repos')
    repos_dir = pjoin(testdir, 'repos')

    @pytest.fixture(autouse=True)
    def _setup(self, testconfig, tmp_path):
        self.cache_dir = str(tmp_path)
        self.args = [
            project, '--config', testconfig,
            'scan', '--config', 'no', '--cache', 'no', '--net',
            '-r', pjoin(self.repos_dir, 'network'),
        ]

    _net_results = []
    for name, cls in sorted(objects.CHECKS.items()):
        if issubclass(cls, NetworkCheck):
            for result in sorted(cls.known_results, key=attrgetter('__name__')):
                _net_results.append((cls, result))

    def _render_results(self, results, **kwargs):
        """Render a given set of result objects into their related string form."""
        with tempfile.TemporaryFile() as f:
            with reporters.FancyReporter(out=PlainTextFormatter(f), **kwargs) as reporter:
                for result in sorted(results):
                    reporter.report(result)
            f.seek(0)
            output = f.read().decode()
            return output

    @pytest.mark.parametrize('check, result', _net_results)
    def test_scan(self, check, result, capsys):
        check_name = check.__name__
        keyword = result.__name__
        result_dir = pjoin(self.repos_dir, 'network', check_name, keyword)

        paths = glob.glob(f'{result_dir}*')
        if not paths:
            pytest.skip('data unavailable')

        for path in paths:
            ebuild_name = os.path.basename(path)
            data_dir = pjoin(self.repos_data, 'network', check_name, ebuild_name)

            # load response data to fake
            module_path = pjoin(path, 'responses.py')
            spec = importlib.util.spec_from_file_location('responses_mod', module_path)
            responses_mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(responses_mod)

            results = []
            args = [
                '-R' 'JsonStream', '-c', check_name, '-k', keyword,
                f'{check_name}/{ebuild_name}'
            ]
            with patch('pkgcheck.net.requests.Session.send') as send:
                with patch('sys.argv', self.args + args):
                    send.side_effect = responses_mod.responses
                    with pytest.raises(SystemExit) as excinfo:
                        self.script()
                    assert excinfo.value.code == 0

                    # load expected results if they exist
                    try:
                        with open(pjoin(data_dir, 'expected.json')) as f:
                            expected_results = set(reporters.JsonStream.from_iter(f))
                    except FileNotFoundError:
                        # check stopped before making request or completed successfully
                        continue

                    out, err = capsys.readouterr()
                    assert out, 'no results exist'
                    for result in reporters.JsonStream.from_iter(io.StringIO(out)):
                        results.append(result)

                    assert expected_results, 'regular results must always exist'
                    rendered_results = self._render_results(results)
                    assert rendered_results, 'failed rendering results'
                    if set(results) != expected_results:
                        error = ['unmatched results:']
                        expected = self._render_results(expected_results)
                        error.append(f'expected:\n{expected}')
                        error.append(f'got:\n{rendered_results}')
                        pytest.fail('\n'.join(error))

    @pytest.mark.parametrize(
        'check, result', ((HomepageUrlCheck, DeadUrl), (FetchablesUrlCheck, DeadUrl)))
    def test_scan_ftp(self, check, result, capsys):
        check_name = check.__name__
        keyword = result.__name__

        pkg = RawCPV(check_name, f'ftp-{keyword}', '0')
        if check_name == 'HomepageUrlCheck':
            deadurl = DeadUrl('HOMEPAGE', 'ftp://pkgcheck.net/pkgcheck/', 'dead ftp', pkg=pkg)
        else:
            deadurl = DeadUrl('SRC_URI', 'ftp://pkgcheck.net/pkgcheck/foo.tar.gz', 'dead ftp', pkg=pkg)

        data = (
            (urllib.error.URLError('dead ftp'), deadurl),
            (socket.timeout('dead ftp'), deadurl),
            (None, None),  # faking a clean connection
        )

        args = [
            '-R', 'JsonStream', '-c', check_name, '-k', keyword,
            f'{check_name}/ftp-{keyword}'
        ]
        for side_effect, expected_result in data:
            with patch('pkgcheck.checks.network.urllib.request.urlopen') as urlopen:
                with patch('sys.argv', self.args + args):
                    if side_effect is not None:
                        urlopen.side_effect = side_effect
                    with pytest.raises(SystemExit) as excinfo:
                        self.script()
                    out, err = capsys.readouterr()
                    assert not err
                    if side_effect is None:
                        assert not out
                    else:
                        assert out, 'no results exist'
                        assert excinfo.value.code == 0
                        results = []
                        for result in reporters.JsonStream.from_iter(io.StringIO(out)):
                            results.append(result)
                        assert len(results) == 1
                        assert results[0] == expected_result
                        assert self._render_results(results), 'failed rendering results'
