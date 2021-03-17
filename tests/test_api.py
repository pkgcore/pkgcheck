import multiprocessing
import os
import signal

import pytest
from pkgcheck import PkgcheckException, scan
from pkgcheck import objects


class TestScanApi:

    @pytest.fixture(autouse=True)
    def _setup(self, testconfig):
        self.base_args = ['--config', testconfig]
        self.scan_args = ['--config', 'no', '--cache', 'no']

    def test_argparse_error(self, repo):
        with pytest.raises(PkgcheckException, match='unrecognized arguments'):
            scan(['-r', repo.location, '--foo'])

    def test_no_scan_args(self):
        pipe = scan(base_args=self.base_args)
        assert pipe.options.target_repo.repo_id == 'standalone'

    def test_no_base_args(self, repo):
        assert [] == list(scan(self.scan_args + ['-r', repo.location]))

    def test_keyword_import(self):
        """Keyword classes are importable from the top-level module."""
        from pkgcheck import NonsolvableDeps, Result
        assert issubclass(NonsolvableDeps, Result)

    def test_module_attributes(self):
        """All keyword class names are shown for the top-level module."""
        import pkgcheck
        assert set(objects.KEYWORDS) < set(dir(pkgcheck))

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
                queue.put('ready')
                time.sleep(100)

            with patch('pkgcheck.pipeline.Pipeline.__iter__') as fake_iter:
                fake_iter.side_effect = partial(sleep)
                try:
                    iter(scan([repo.location]))
                except KeyboardInterrupt:
                    queue.put(None)
                    sys.exit(0)
                queue.put(None)
                sys.exit(1)

        mp_ctx = multiprocessing.get_context('fork')
        queue = mp_ctx.SimpleQueue()
        p = mp_ctx.Process(target=run, args=(queue,))
        p.start()
        # wait for pipeline object to be fully initialized then send SIGINT
        for _ in iter(queue.get, None):
            os.kill(p.pid, signal.SIGINT)
            p.join()
            assert p.exitcode == 0
