"""Pipeline building support for connecting sources and checks."""

import multiprocessing
import os
import signal
import traceback
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from itertools import chain, tee

from pkgcore.package.errors import MetadataException
from pkgcore.restrictions import packages

from . import base
from .checks import init_checks
from .results import MetadataError
from .sources import UnversionedSource, VersionedSource


class Pipeline:
    """Check-running pipeline leveraging scope-based parallelism.

    All results are pushed into the results queue as lists of result objects or
    exception traceback strings. This iterator forces exceptions to be handled
    explicitly by outputting the serialized traceback and signaling the process
    group to end when an exception is raised.
    """

    def __init__(self, options, restrictions):
        self.options = options
        self._restrictions = (x for _scope, x in restrictions)
        # number of error results encountered (used with --exit option)
        self.errors = 0

        # pkgcheck currently requires the fork start method (#254)
        self._mp_ctx = multiprocessing.get_context('fork')
        # create checkrunner pipelines
        self._results_q = self._mp_ctx.SimpleQueue()
        self._pipes = self._create_runners()

        # initialize settings used by iterator support
        self._pid = None
        signal.signal(signal.SIGINT, self._kill_pipe)
        self._results_iter = iter(self._results_q.get, None)
        self._results = deque()

        # scoped mapping for caching repo and location specific results
        self._sorted_results = {
            scope: [] for scope in reversed(list(base.scopes.values()))
            if scope.level <= base.repo_scope
        }

        # package level scans sort all returned results
        if self.options.pkg_scan:
            self._sorted_results.update({
                scope: [] for scope in base.scopes.values()
                if scope.level >= base.package_scope
            })

    def _create_runners(self):
        """Initialize and categorize checkrunners for results pipeline."""
        # initialize enabled checks
        enabled_checks = init_checks(self.options.addons, self.options, self._results_q)

        # initialize checkrunners per source type, using separate runner for async checks
        checkrunners = defaultdict(list)
        runner_cls_map = {'async': AsyncCheckRunner, 'sync': SyncCheckRunner}
        for (source, exec_type), checks in enabled_checks.items():
            runner = runner_cls_map[exec_type](self.options, source, checks)
            checkrunners[(source.scope, exec_type)].append(runner)

        # categorize checkrunners for parallelization based on the scan and source scope
        pipes = defaultdict(lambda: defaultdict(list))
        if self.options.pkg_scan:
            for (scope, exec_type), runners in checkrunners.items():
                if scope is base.version_scope:
                    pipes[exec_type][base.version_scope].extend(runners)
                else:
                    pipes[exec_type][base.package_scope].extend(runners)
        else:
            for (scope, exec_type), runners in checkrunners.items():
                if scope in (base.version_scope, base.package_scope):
                    pipes[exec_type][base.package_scope].extend(runners)
                else:
                    pipes[exec_type][scope].extend(runners)

        return pipes

    def _kill_pipe(self, *args, error=None):
        """Handle terminating the pipeline process group."""
        if self._pid is not None:
            os.killpg(self._pid, signal.SIGKILL)
        if error is not None:
            # propagate exception raised during parallel scan
            raise base.PkgcheckException(error)
        raise KeyboardInterrupt

    def __iter__(self):
        # start running the check pipeline
        p = self._mp_ctx.Process(target=self._run)
        p.start()
        self._pid = p.pid
        return self

    def __next__(self):
        while True:
            try:
                result = self._results.popleft()
                if not result.filtered and result.__class__ in self.options.filtered_keywords:
                    if result.__class__ in self.options.exit_keywords:
                        self.errors += 1
                    return result
            except IndexError:
                try:
                    results = next(self._results_iter)
                except StopIteration:
                    if self._sorted_results is None:
                        raise
                    self._pid = None
                    # return cached repo and location specific results
                    results = chain.from_iterable(map(sorted, self._sorted_results.values()))
                    self._results.extend(results)
                    self._sorted_results = None
                    continue

                # Catch propagated exceptions, output their traceback, and
                # signal the scanning process to end.
                if isinstance(results, str):
                    self._kill_pipe(error=results.strip())

                if self.options.pkg_scan:
                    # Sort all generated results when running at package scope
                    # level, i.e. running within a package directory in an
                    # ebuild repo.
                    for result in results:
                        self._sorted_results[result.scope].append(result)
                else:
                    # Running at a category scope level or higher. This outputs
                    # version/package/category results in a stream sorted per package
                    # while caching any repo, commit, and specific location (e.g.
                    # profiles or eclass) results. Those are then outputted in sorted
                    # fashion in order of their scope level from greatest to least
                    # (displaying repo results first) after all
                    # version/package/category results have been output.
                    for result in sorted(results):
                        try:
                            self._sorted_results[result.scope].append(result)
                        except KeyError:
                            self._results.append(result)

    def _queue_work(self, sync_pipes, work_q, restrictions):
        """Producer that queues scanning tasks against granular scope restrictions."""
        for restriction in restrictions:
            for scope in sorted(sync_pipes, reverse=True):
                pipes = sync_pipes[scope]
                if scope is base.version_scope:
                    versioned_source = VersionedSource(self.options)
                    for restrict in versioned_source.itermatch(restriction):
                        for i in range(len(pipes)):
                            work_q.put((scope, restrict, i))
                elif scope is base.package_scope:
                    unversioned_source = UnversionedSource(self.options)
                    for restrict in unversioned_source.itermatch(restriction):
                        work_q.put((scope, restrict, 0))
                else:
                    for i in range(len(pipes)):
                        work_q.put((scope, restriction, i))

        # notify consumers that no more work exists
        for i in range(self.options.jobs):
            work_q.put(None)

    def _run_checks(self, pipes, work_q):
        """Consumer that runs scanning tasks, queuing results for output."""
        try:
            for scope, restrict, pipe_idx in iter(work_q.get, None):
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
                    self._results_q.put(results)
        except Exception:  # pragma: no cover
            # traceback can't be pickled so serialize it
            tb = traceback.format_exc()
            self._results_q.put(tb)

    def _schedule_async(self, pipes, restrictions):
        """Schedule asynchronous checks."""
        try:
            with ThreadPoolExecutor(max_workers=self.options.tasks) as executor:
                # schedule any existing async checks
                futures = {}
                for restrict in restrictions:
                    for runner in chain.from_iterable(pipes):
                        runner.schedule(executor, futures, restrict)
        except Exception:  # pragma: no cover
            # traceback can't be pickled so serialize it
            tb = traceback.format_exc()
            self._results_q.put(tb)

    def _run(self):
        """Run the scanning pipeline in parallel by check and scanning scope."""
        try:
            signal.signal(signal.SIGINT, signal.SIG_DFL)
            os.setpgrp()
            async_restricts, sync_restricts = tee(self._restrictions)

            # schedule asynchronous checks in a separate process
            async_proc = None
            if async_pipes := self._pipes['async'].values():
                async_proc = self._mp_ctx.Process(
                    target=self._schedule_async, args=(async_pipes, async_restricts))
                async_proc.start()

            # run synchronous checks using a process pool
            if sync_pipes := self._pipes['sync']:
                work_q = self._mp_ctx.SimpleQueue()
                pool = self._mp_ctx.Pool(
                    self.options.jobs, self._run_checks, (sync_pipes, work_q))
                pool.close()
                self._queue_work(sync_pipes, work_q, sync_restricts)
                pool.join()

            if async_proc is not None:
                async_proc.join()
            # notify iterator that no more results exist
            self._results_q.put(None)
        except Exception:  # pragma: no cover
            # traceback can't be pickled so serialize it
            tb = traceback.format_exc()
            self._results_q.put(tb)


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


class SyncCheckRunner(CheckRunner):
    """Generic runner for synchronous checks."""

    def __init__(self, *args):
        super().__init__(*args)
        # set of known results for all checks run by the checkrunner
        self._known_results = set().union(*(x.known_results for x in self.checks))
        # used to store MetadataError results for processing
        self._metadata_errors = deque()

        # only report metadata errors for version-scoped sources
        if self.source.scope is base.version_scope:
            self.source.itermatch = partial(
                self.source.itermatch, error_callback=self._metadata_error_cb)

    def _metadata_error_cb(self, e, check=None):
        """Callback handling MetadataError results."""
        # Errors thrown by pkgcore during itermatch() aren't in check running
        # context so use all known results for the checkrunner in that case.
        if check is None:
            known_results = self._known_results
        else:
            known_results = check.known_results

        # Unregistered metadata attrs will raise KeyError here which is wanted
        # so they can be noticed and fixed.
        result_cls = MetadataError.result_mapping[e.attr]
        if result_cls in known_results:
            error_str = ': '.join(e.msg().split('\n'))
            result = result_cls(e.attr, error_str, pkg=e.pkg)
            self._metadata_errors.append((e.pkg, result))

    def start(self):
        """Run all check start methods."""
        for check in self.checks:
            check.start()

    def run(self, restrict=packages.AlwaysTrue):
        """Run registered checks against all matching source items."""
        for item in self.source.itermatch(restrict):
            for check in self.checks:
                try:
                    yield from check.feed(item)
                except MetadataException as e:
                    self._metadata_error_cb(e, check=check)

        # yield all relevant MetadataError results that occurred
        while self._metadata_errors:
            pkg, result = self._metadata_errors.popleft()
            if restrict.match(pkg):
                yield result

    def finish(self):
        """Run all check finish methods while yielding any results."""
        for check in self.checks:
            yield from check.finish()


class AsyncCheckRunner(CheckRunner):
    """Generic runner for asynchronous checks.

    Checks that would otherwise block for uncertain amounts of time due to I/O
    or network access are run in separate threads, queuing any relevant results
    on completion.
    """
    def schedule(self, executor, futures, restrict=packages.AlwaysTrue):
        """Schedule all checks to run via the given executor."""
        for item in self.source.itermatch(restrict):
            for check in self.checks:
                check.schedule(item, executor, futures)
