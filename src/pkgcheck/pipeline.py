"""Pipeline building support for connecting sources and checks."""

import os
import signal
import sys
import traceback
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from multiprocessing import Pool, Process, SimpleQueue

from pkgcore.package.errors import MetadataException
from pkgcore.restrictions import boolean, packages
from snakeoil.currying import post_curry

from . import base
from .results import MetadataError
from .sources import UnversionedSource, VersionedSource


class Pipeline:
    """Check-running pipeline leveraging scope-based parallelism.

    All results are pushed into the results queue as lists of result objects or
    exception tuples. This iterator forces exceptions to be handled explicitly,
    by outputing the serialized traceback and signaling scanning processes to
    end when an exception object is found.
    """

    def __init__(self, options, scan_scope, pipes, restriction):
        self.options = options
        self.scan_scope = scan_scope
        self.restriction = restriction
        self.results_q = SimpleQueue()
        self.work_q = SimpleQueue()
        self._iter = iter(self.results_q.get, None)
        self._pid = None

        # determine if scan is being run at a package level
        self.pkg_scan = (
            scan_scope in (base.version_scope, base.package_scope) and
            isinstance(restriction, boolean.AndRestriction))

        # initialize checkrunners per source type, using separate runner for async checks
        checkrunners = defaultdict(list)
        for (source, exec_type), checks in pipes.items():
            if exec_type == 'async':
                runner = AsyncCheckRunner(
                    self.options, source, checks, results_q=self.results_q)
            else:
                runner = CheckRunner(self.options, source, checks)
            checkrunners[(source.scope, exec_type)].append(runner)

        # categorize checkrunners for parallelization based on the scan and source scope
        self.scoped_pipes = defaultdict(lambda: defaultdict(list))
        if self.pkg_scan:
            for (scope, exec_type), runners in checkrunners.items():
                if scope is base.version_scope:
                    self.scoped_pipes[exec_type][base.version_scope].extend(runners)
                else:
                    self.scoped_pipes[exec_type][base.package_scope].extend(runners)
        else:
            for (scope, exec_type), runners in checkrunners.items():
                if scope in (base.version_scope, base.package_scope):
                    self.scoped_pipes[exec_type][base.package_scope].extend(runners)
                else:
                    self.scoped_pipes[exec_type][scope].extend(runners)

    def _kill_pipe(self, *args, exit=False):
        if self._pid is not None:
            os.killpg(self._pid, signal.SIGKILL)
        if exit:
            raise SystemExit(1)
        raise KeyboardInterrupt

    def __iter__(self):
        # start running the check pipeline
        signal.signal(signal.SIGINT, self._kill_pipe)
        p = Process(target=self._run)
        p.start()
        self._pid = p.pid
        return self

    def __next__(self):
        results = next(self._iter)
        # Catch propagated exceptions, output their traceback, and
        # signal the scanning process to end.
        if isinstance(results, str):
            print(results.strip(), file=sys.stderr)
            self._kill_pipe(exit=True)
        return results

    def _queue_work(self):
        """Producer that queues scanning tasks against granular scope restrictions."""
        try:
            for scope in sorted(self.scoped_pipes['sync'], reverse=True):
                pipes = self.scoped_pipes['sync'][scope]
                if scope is base.version_scope:
                    versioned_source = VersionedSource(self.options)
                    for restrict in versioned_source.itermatch(self.restriction):
                        for i in range(len(pipes)):
                            self.work_q.put((scope, restrict, i))
                elif scope is base.package_scope:
                    unversioned_source = UnversionedSource(self.options)
                    for restrict in unversioned_source.itermatch(self.restriction):
                        self.work_q.put((scope, restrict, 0))
                else:
                    for i in range(len(pipes)):
                        self.work_q.put((scope, self.restriction, i))

            # insert flags to notify consumers that no more work exists
            for i in range(self.options.jobs):
                self.work_q.put(None)

            # schedule all async checks from a single process
            for scope, pipes in self.scoped_pipes['async'].items():
                for pipe in pipes:
                    pipe.run(self.restriction)
        except Exception:
            # traceback can't be pickled so serialize it
            tb = traceback.format_exc()
            self.results_q.put(tb)

    def _run_checks(self):
        """Consumer that runs scanning tasks, queuing results for output."""
        pipes = self.scoped_pipes['sync']
        try:
            for scope, restrict, pipe_idx in iter(self.work_q.get, None):
                results = []

                if scope is base.version_scope:
                    results.extend(pipes[scope][pipe_idx].run(restrict))
                elif scope in (base.package_scope, base.category_scope):
                    for pipe in pipes[scope]:
                        results.extend(pipe.run(restrict))
                else:
                    pipe = pipes[scope][pipe_idx]
                    pipe.start()
                    results.extend(pipe.run(restrict))
                    results.extend(pipe.finish())

                if results:
                    self.results_q.put(results)
        except Exception:
            # traceback can't be pickled so serialize it
            tb = traceback.format_exc()
            self.results_q.put(tb)

    def _run(self):
        """Run the scanning pipeline in parallel by check and scanning scope."""
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        os.setpgrp()
        # run synchronous checks using process pool, queuing generated results for reporting
        pool = Pool(self.options.jobs, self._run_checks)
        pool.close()
        # split target restriction into tasks for parallelization
        self._queue_work()
        pool.join()
        self.results_q.put(None)
        os._exit(0)


class CheckRunner:
    """Generic runner for checks.

    Checks are run in order of priority. Some checks need to be run before
    others if both are enabled due to package attribute caching in pkgcore,
    e.g. checks that test depset parsing need to come before other checks that
    use the parsed deps otherwise results from parsing errors could be missed.
    """

    def __init__(self, options, source, checks):
        self.options = options
        self.source = source
        self.checks = tuple(sorted(checks))
        self._running_check = None
        self._known_results = set().union(*(x.known_results for x in self.checks))

        # only report metadata errors when running at version level
        if self.source.scope is base.version_scope:
            self._source_itermatch = post_curry(
                self.source.itermatch, error_callback=self._metadata_error_cb)
        else:
            self._source_itermatch = self.source.itermatch

        self._metadata_errors = deque()

    def _metadata_error_cb(self, e):
        """Callback handling MetadataError related results."""
        # Unregistered metadata attrs will raise KeyError here which is wanted
        # so they can be noticed and fixed.
        cls = MetadataError.result_mapping[e.attr]
        if cls in getattr(self._running_check, 'known_results', self._known_results):
            error_str = ': '.join(e.msg().split('\n'))
            result = cls(e.attr, error_str, pkg=e.pkg)
            self._metadata_errors.append((e.pkg, result))

    def start(self):
        for check in self.checks:
            check.start()

    def run(self, restrict=packages.AlwaysTrue):
        """Run registered checks against all matching source items."""
        for item in self._source_itermatch(restrict):
            for check in self.checks:
                self._running_check = check
                try:
                    yield from check.feed(item)
                except MetadataException as e:
                    self._metadata_error_cb(e)
            self._running_check = None

        while self._metadata_errors:
            pkg, result = self._metadata_errors.popleft()
            # Only show metadata errors for packages matching the current
            # restriction to avoid duplicate reports.
            if restrict.match(pkg):
                yield result

    def finish(self):
        for check in self.checks:
            yield from check.finish()


class AsyncCheckRunner(CheckRunner):
    """Generic runner for asynchronous checks.

    Checks that would otherwise block for uncertain amounts of time due to I/O
    or network access are run in separate threads, queuing any relevant results
    on completion.
    """
    def __init__(self, *args, results_q):
        super().__init__(*args)
        self.results_q = results_q

    def run(self, restrict=packages.AlwaysTrue):
        with ThreadPoolExecutor(max_workers=self.options.tasks) as executor:
            futures = {}
            for item in self._source_itermatch(restrict):
                for check in self.checks:
                    check.schedule(item, executor, futures, self.results_q)
