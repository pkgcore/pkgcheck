import importlib.util
import os
import socket
import tempfile
import urllib.request
from functools import partial
from operator import attrgetter
from unittest.mock import patch

import pytest
from pkgcheck import objects, reporters, scan
from pkgcheck.checks import NetworkCheck
from pkgcheck.checks.network import DeadUrl, FetchablesUrlCheck, HomepageUrlCheck
from pkgcheck.packages import RawCPV
from snakeoil.formatters import PlainTextFormatter

# skip module tests if requests isn't available
requests = pytest.importorskip("requests")


class TestNetworkChecks:
    repos_data = pytest.REPO_ROOT / "testdata/data/repos"
    repos_dir = pytest.REPO_ROOT / "testdata/repos"

    @pytest.fixture(autouse=True)
    def _setup(self, testconfig, tmp_path):
        base_args = ["--config", testconfig]
        self.scan = partial(scan, base_args=base_args)
        self.scan_args = [
            "--config",
            "no",
            "--cache-dir",
            str(tmp_path),
            "--net",
            "-r",
            str(self.repos_dir / "network"),
        ]

    _net_results = [
        (cls, result)
        for _name, cls in sorted(objects.CHECKS.items())
        if issubclass(cls, NetworkCheck)
        for result in sorted(cls.known_results, key=attrgetter("__name__"))
    ]

    def _render_results(self, results, **kwargs):
        """Render a given set of result objects into their related string form."""
        with tempfile.TemporaryFile() as f:
            with reporters.FancyReporter(out=PlainTextFormatter(f), **kwargs) as reporter:
                for result in sorted(results):
                    reporter.report(result)
            f.seek(0)
            output = f.read().decode()
            return output

    @pytest.mark.parametrize("check, result", _net_results)
    def test_scan(self, check, result):
        check_name = check.__name__
        keyword = result.__name__

        result_dir = self.repos_dir / "network" / check_name
        paths = tuple(result_dir.glob(keyword + "*"))
        if not paths:
            pytest.skip("data unavailable")

        for path in paths:
            ebuild_name = os.path.basename(path)
            data_dir = self.repos_data / "network" / check_name / ebuild_name

            # load response data to fake
            module_path = path / "responses.py"
            spec = importlib.util.spec_from_file_location("responses_mod", module_path)
            responses_mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(responses_mod)

            results = []
            args = ["-c", check_name, "-k", keyword, f"{check_name}/{ebuild_name}"]
            with patch("pkgcheck.addons.net.requests.Session.send") as send:
                send.side_effect = responses_mod.responses

                # load expected results if they exist
                try:
                    with (data_dir / "expected.json").open() as f:
                        expected_results = set(reporters.JsonStream.from_iter(f))
                except FileNotFoundError:
                    # check stopped before making request or completed successfully
                    continue

                results = list(self.scan(self.scan_args + args))
                rendered_results = self._render_results(results)
                assert rendered_results, "failed rendering results"
                if set(results) != expected_results:
                    error = ["unmatched results:"]
                    expected = self._render_results(expected_results)
                    error.append(f"expected:\n{expected}")
                    error.append(f"got:\n{rendered_results}")
                    pytest.fail("\n".join(error))

    @pytest.mark.parametrize(
        "check, result",
        (
            (HomepageUrlCheck, DeadUrl),
            (FetchablesUrlCheck, DeadUrl),
        ),
    )
    def test_scan_ftp(self, check, result):
        check_name = check.__name__
        keyword = result.__name__

        pkg = RawCPV(check_name, f"ftp-{keyword}", "0")
        if check_name == "HomepageUrlCheck":
            deadurl = DeadUrl("HOMEPAGE", "ftp://pkgcheck.net/pkgcheck/", "dead ftp", pkg=pkg)
        else:
            deadurl = DeadUrl(
                "SRC_URI", "ftp://pkgcheck.net/pkgcheck/foo.tar.gz", "dead ftp", pkg=pkg
            )

        data = (
            (urllib.error.URLError("dead ftp"), deadurl),
            (socket.timeout("dead ftp"), deadurl),
            (None, None),  # faking a clean connection
        )

        args = ["-c", check_name, "-k", keyword, f"{check_name}/ftp-{keyword}"]
        for side_effect, expected_result in data:
            with patch("pkgcheck.checks.network.urllib.request.urlopen") as urlopen:
                if side_effect is not None:
                    urlopen.side_effect = side_effect
                results = list(self.scan(self.scan_args + args))
                if side_effect is None:
                    assert not results
                else:
                    assert results == [expected_result]
                    assert self._render_results(results), "failed rendering results"
