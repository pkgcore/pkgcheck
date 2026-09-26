import contextlib
import ctypes
import faulthandler
import multiprocessing
import os
import re
import signal
from unittest.mock import patch

import pytest

from pkgcheck import PkgcheckException, scan
from pkgcheck.checks.codingstyle import BadCommandsCheck
from pkgcheck.pipeline import Pipeline
from pkgcheck.sources import UnversionedSource


def _segfault(self, pkg):
    """Segfault the worker the way a broken C extension would."""
    faulthandler.disable()  # pytest enables faulthandler, which the worker inherits over fork
    ctypes.CDLL(None).prctl(4, 0, 0, 0, 0)  # PR_SET_DUMPABLE, so no core gets collected
    ctypes.string_at(0)


class TestScanApi:
    @pytest.fixture(autouse=True)
    def _setup(self, testconfig):
        self.base_args = ["--config", testconfig]
        self.scan_args = ["--config", "no", "--cache", "no"]

    def test_argparse_error(self, repo):
        with pytest.raises(PkgcheckException, match="unrecognized arguments"):
            scan(["-r", repo.location, "--foo"])

    def test_no_scan_args(self):
        pipe = scan(base_args=self.base_args)
        assert pipe.options.target_repo.repo_id == "standalone"

    def test_no_base_args(self, repo):
        assert [] == list(scan(self.scan_args + ["-r", repo.location]))

    def test_sigint_handling(self, repo):
        """Verify SIGINT is properly handled by the parallelized pipeline."""

        def run(queue):
            """Pipeline test run in a separate process that gets interrupted."""
            import sys
            import time
            from functools import partial
            from unittest.mock import patch

            from pkgcheck import scan

            def sleep():
                """Notify testing process then sleep."""
                queue.put("ready")
                time.sleep(100)

            with patch("pkgcheck.pipeline.Pipeline.__iter__") as fake_iter:
                fake_iter.side_effect = partial(sleep)
                try:
                    iter(scan([repo.location]))
                except KeyboardInterrupt:
                    queue.put(None)
                    sys.exit(0)
                queue.put(None)
                sys.exit(1)

        mp_ctx = multiprocessing.get_context("fork")
        queue = mp_ctx.SimpleQueue()
        p = mp_ctx.Process(target=run, args=(queue,))
        p.start()
        # wait for pipeline object to be fully initialized then send SIGINT
        for _ in iter(queue.get, None):
            os.kill(p.pid, signal.SIGINT)
            p.join()
            assert p.exitcode == 0

    def test_worker_crash_handling(self):
        standalone = str(pytest.REPO_ROOT / "testdata/repos/standalone")
        target = "BadCommandsCheck/BannedEapiCommand"
        args = self.scan_args + ["-r", standalone, target]

        assert list(scan(args)), "expected results from an uncrashed scan"

        with (
            patch.object(BadCommandsCheck, "feed", _segfault),
            pytest.raises(PkgcheckException, match="killed by SIGSEGV"),
        ):
            list(scan(args))

    @staticmethod
    def _assert_scan_fails(args, match, *patches):
        """Scan in a child process, so that a hang fails the test rather than the suite."""

        def run():
            with contextlib.ExitStack() as stack:
                for p in patches:
                    stack.enter_context(p)
                try:
                    list(scan(args))
                except PkgcheckException as e:
                    os._exit(0 if re.search(match, str(e)) else 2)
            os._exit(1)

        proc = multiprocessing.get_context("fork").Process(target=run)
        proc.start()
        proc.join(60)
        if proc.is_alive():
            proc.kill()
            proc.join()
            pytest.fail("scan hung")
        assert proc.exitcode == 0

    @pytest.mark.parametrize("jobs", (1, 4))
    def test_all_workers_crash(self, jobs):
        standalone = str(pytest.REPO_ROOT / "testdata/repos/standalone")
        args = self.scan_args + ["-r", standalone, "-c", "BadCommandsCheck", "-j", str(jobs)]
        itermatch = UnversionedSource.itermatch

        def flood(self, *args, **kwargs):
            for pkg in itermatch(self, *args, **kwargs):
                yield from [pkg] * 500

        self._assert_scan_fails(
            args,
            "killed by SIGSEGV",
            patch.object(BadCommandsCheck, "feed", _segfault),
            patch.object(UnversionedSource, "itermatch", flood),
        )

    def test_pipeline_crash(self):
        standalone = str(pytest.REPO_ROOT / "testdata/repos/standalone")
        args = self.scan_args + ["-r", standalone, "-c", "BadCommandsCheck"]

        def die(self, *args):
            os.kill(os.getpid(), signal.SIGKILL)

        self._assert_scan_fails(
            args, "scan pipeline killed by SIGKILL", patch.object(Pipeline, "_queue_work", die)
        )
