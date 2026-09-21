"""Pipeline that parallelizes check running."""

import multiprocessing
import os
import signal
import threading
import traceback
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from itertools import chain
from operator import attrgetter

from . import base
from .checks import init_checks
from .jobserver import JobServer
from .sources import UnversionedSource, VersionedSource

# Tasks that have to be queued before another check runner earns a job token.
# Forking one and holding a token for the rest of the scan only pays off if
# there is a backlog to work through, so small scans stay small.
_WORK_PER_RUNNER = 32


class Pipeline:
    """Check-running pipeline leveraging scope-based parallelism.

    All results are pushed into the results queue as lists of result objects or
    exception traceback strings. This iterator forces exceptions to be handled
    explicitly by outputting the serialized traceback and signaling the process
    group to end when an exception is raised.
    """

    def __init__(self, options):
        self.options = options
        # results flagged as errors by the --exit option
        self.errors = []

        # pkgcheck currently requires the fork start method (#254)
        self._mp_ctx = multiprocessing.get_context("fork")
        self._results_q = self._mp_ctx.SimpleQueue()

        # create checkrunners
        self._pipes = self._create_runners()

        # initialize settings used by iterator support
        self._runner = self._mp_ctx.Process(target=self._run)
        signal.signal(signal.SIGINT, self._kill_pipe)
        self._results_iter = iter(self._results_q.get, None)
        self._results = deque()

        if self.options.pkg_scan:
            # package level scans sort all returned results
            self._ordered_results = {
                scope: [] for scope in base.scopes.values() if scope >= base.package_scope
            }
        else:
            # scoped mapping for caching repo and location specific results
            self._ordered_results = {
                scope: []
                for scope in reversed(list(base.scopes.values()))
                if scope <= base.repo_scope
            }

    def _filter_checks(self, scope):
        """Verify check scope against given scope to determine activation."""
        for check in sorted(self.options.enabled_checks, key=attrgetter("__name__")):
            if isinstance(check.scope, base.ConditionalScope):
                # conditionally enabled check
                yield check
            elif isinstance(check.scope, base.LocationScope):
                if not self.options.selected_scopes:
                    if scope == base.repo_scope or check.scope in scope:
                        # allow repo scans or cwd scope to trigger location specific checks
                        yield check
                elif check.scope in self.options.selected_scopes:
                    # Allow checks with special scopes to be run when specifically
                    # requested, e.g. eclass-only scanning.
                    yield check
            elif isinstance(scope, base.PackageScope) and check.scope >= scope:
                # Only run pkg-related checks at or below the current scan scope level, if
                # pkg scanning is requested, e.g. skip repo level checks when scanning at
                # package level.
                yield check

    def _create_runners(self):
        """Initialize and categorize checkrunners for results pipeline."""
        pipes = {"async": [], "sync": [], "sequential": []}

        # use addon/source caches to avoid re-initializing objects
        addons_map = {}
        source_map = {}

        for scope, restriction in self.options.restrictions:
            # initialize enabled checks
            addons = list(base.get_addons(self._filter_checks(scope)))
            if not addons:
                raise base.PkgcheckUserException(
                    f"no matching checks available for {scope.desc} scope"
                )
            checks = init_checks(
                addons, self.options, self._results_q, addons_map=addons_map, source_map=source_map
            )

            # Initialize checkrunners per source type using separate runner for
            # async checks and categorize them for parallelization based on the
            # scan and source scope.
            runners = {
                "async": defaultdict(list),
                "sync": defaultdict(list),
                "sequential": defaultdict(list),
            }
            for (source, runner_cls), check_objs in checks.items():
                runner = runner_cls(self.options, source, check_objs)
                if not self.options.pkg_scan and source.scope >= base.package_scope:
                    runners[runner_cls.type][base.package_scope].append(runner)
                else:
                    runners[runner_cls.type][source.scope].append(runner)

            for exec_type, pipe in pipes.items():
                if runners[exec_type]:
                    pipe.append((scope, restriction, runners[exec_type]))

        return pipes

    def _kill_pipe(self, *args, error=None):
        """Handle terminating the pipeline process group."""
        if self._runner.is_alive():
            os.killpg(self._runner.pid, signal.SIGKILL)
        if error is not None:
            # propagate exception raised during parallel scan
            raise base.PkgcheckUserException(error)
        raise KeyboardInterrupt

    def __iter__(self):
        # start running the check pipeline
        self._runner.start()
        return self

    def __next__(self):
        while True:
            try:
                result = self._results.popleft()
                if not result._filtered and result.__class__ in self.options.filtered_keywords:
                    if result.__class__ in self.options.exit_keywords:
                        self.errors.append(result)
                    return result
            except IndexError:
                try:
                    results = next(self._results_iter)
                except StopIteration:
                    if self._ordered_results is None:
                        raise
                    self._runner.join()
                    # output cached results in registered order
                    results = chain.from_iterable(map(sorted, self._ordered_results.values()))
                    self._results.extend(results)
                    self._ordered_results = None
                    continue

                # Catch propagated, serialized exceptions, output their
                # traceback, and signal the scanning process to end.
                if isinstance(results, str):
                    self._kill_pipe(error=results.strip())

                # cache registered result scopes to forcibly order output
                try:
                    self._ordered_results[results[0].scope].extend(results)
                except KeyError:
                    self._results.extend(results)

    def _queue_work(self, sync_pipes, work_q):
        """Producer that queues scanning tasks against granular scope restrictions."""
        versioned_source = VersionedSource(self.options)
        unversioned_source = UnversionedSource(self.options)
        queued = 0

        def queue(work):
            """Queue a task, crediting a runner once enough of them pile up."""
            nonlocal queued
            work_q.put(work)
            queued += 1
            if not queued % _WORK_PER_RUNNER:
                self._work_credits.release()

        for i, (scan_scope, restriction, pipes) in enumerate(sync_pipes):
            for scope, runners in pipes.items():
                num_runners = len(runners)
                if base.version_scope in (scope, scan_scope):
                    for restrict in versioned_source.itermatch(restriction):
                        for j in range(num_runners):
                            queue((scope, restrict, i, [j]))
                elif scope == base.package_scope:
                    for restrict in unversioned_source.itermatch(restriction):
                        queue((scope, restrict, i, range(num_runners)))
                else:
                    for j in range(num_runners):
                        queue((scope, restriction, i, [j]))

        # notify a consumer that no more work exists
        work_q.put(None)

    def _run_checks(self, pipes, work_q):
        """Consumer that runs scanning tasks, queuing results for output."""
        try:
            for scope, restrict, i, runners in iter(work_q.get, None):
                if results := sorted(
                    chain.from_iterable(pipes[i][-1][scope][j].run(restrict) for j in runners)
                ):
                    self._results_q.put(results)
        except Exception:  # pragma: no cover
            # traceback can't be pickled so serialize it
            tb = traceback.format_exc()
            self._results_q.put(tb)
        finally:
            # pass the notice on, so that the number of consumers, which grows
            # while work is being queued, doesn't have to be known in advance
            work_q.put(None)

    def _schedule_async(self, async_pipes):
        """Schedule asynchronous checks."""
        try:
            with ThreadPoolExecutor(max_workers=self.options.tasks) as executor:
                # schedule any existing async checks
                futures = {}
                for _scope, restriction, pipes in async_pipes:
                    for runner in chain.from_iterable(pipes.values()):
                        runner.schedule(executor, futures, restriction)
        except Exception:  # pragma: no cover
            # traceback can't be pickled so serialize it
            tb = traceback.format_exc()
            self._results_q.put(tb)

    def _start_worker(self, sync_pipes, work_q, num):
        """Start a worker process consuming scanning tasks."""
        worker = self._mp_ctx.Process(
            target=self._run_checks,
            args=(sync_pipes, work_q),
            name=f"check runner {num}",
            daemon=True,
        )
        worker.start()
        return worker

    def _grow_workers(self, sync_pipes, work_q, workers, jobserver):
        """Start further workers as work piles up and the jobserver allows.

        Waiting for the work before the token keeps a scan from sitting on
        tokens it has nothing to do with, which matters when the pool is busy:
        a token held here is one every other job on the machine has to wait for.
        """
        while len(workers) < self.options.jobs:
            self._work_credits.acquire()
            if not self._growing or not jobserver.acquire():
                break
            workers.append(self._start_worker(sync_pipes, work_q, len(workers)))

    def _check_exitcode(self, proc):
        """Report a child process that terminated abnormally."""
        if exitcode := proc.exitcode:
            if exitcode < 0:
                reason = f"killed by {signal.Signals(-exitcode).name}"
            else:
                reason = f"exited with status {exitcode}"
            self._results_q.put(f"{proc.name} {reason}, results are incomplete")

    def _run(self):
        """Run the scanning pipeline in parallel by check and scanning scope."""
        try:
            signal.signal(signal.SIGINT, signal.SIG_DFL)
            os.setpgrp()

            # schedule asynchronous checks in a separate process
            async_proc = None
            if async_pipes := self._pipes["async"]:
                async_proc = self._mp_ctx.Process(
                    target=self._schedule_async, args=(async_pipes,), name="async check scheduler"
                )
                async_proc.start()

            # run synchronous checks using a set of worker processes
            if sync_pipes := self._pipes["sync"]:
                work_q = self._mp_ctx.SimpleQueue()
                self._work_credits = threading.Semaphore(0)
                self._growing = True
                with JobServer.connect() as jobserver:
                    grower = None
                    if jobserver:
                        # The first runner is free, running on the job this process
                        # was itself started for. The rest have to be paid for, so
                        # they're started as tokens turn up instead of up front.
                        workers = [self._start_worker(sync_pipes, work_q, 0)]
                        grower = threading.Thread(
                            target=self._grow_workers,
                            args=(sync_pipes, work_q, workers, jobserver),
                            name="check runner spawner",
                            daemon=True,
                        )
                        grower.start()
                    else:
                        workers = [
                            self._start_worker(sync_pipes, work_q, i)
                            for i in range(self.options.jobs)
                        ]

                    try:
                        self._queue_work(sync_pipes, work_q)
                        if grower is not None:
                            # a worker exiting means the queue drained, leaving
                            # nothing for a newly started one to do
                            workers[0].join()
                    finally:
                        # unblock the spawner whichever of the two it waits on
                        self._growing = False
                        self._work_credits.release()
                        jobserver.stop()
                        if grower is not None:
                            grower.join()

                    for worker in workers:
                        worker.join()
                        self._check_exitcode(worker)

            if sequential_pipes := self._pipes["sequential"]:
                for _scope, restriction, pipes in sequential_pipes:
                    for runner in chain.from_iterable(pipes.values()):
                        if results := tuple(runner.run(restriction)):
                            self._results_q.put(results)

            if async_proc is not None:
                async_proc.join()
                self._check_exitcode(async_proc)
            # notify iterator that no more results exist
            self._results_q.put(None)
        except Exception:  # pragma: no cover
            # traceback can't be pickled so serialize it
            tb = traceback.format_exc()
            self._results_q.put(tb)
