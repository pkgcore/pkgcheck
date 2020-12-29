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
from pkgcore.restrictions import boolean, packages

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
        # number of error results encountered (used with --exit option)
        self.errors = 0

        # pull scan scope from the given restriction targets
        restrictions = iter(restrictions)
        try:
            scan_scope, restriction = next(restrictions)
        except StopIteration:
            raise base.PkgcheckUserException('no targets piped in')
        self._restrictions = chain([restriction], (x for _scope, x in restrictions))

        # determine if scan is being run at a package level
        pkg_scan = (
            scan_scope in (base.version_scope, base.package_scope) and
            isinstance(restriction, boolean.AndRestriction))

        # pkgcheck currently requires the fork start method (#254)
        self._mp_ctx = multiprocessing.get_context('fork')
        self._results_q = self._mp_ctx.SimpleQueue()

        # create checkrunners
        self._pipes = self._create_runners(scan_scope, pkg_scan)

        # initialize settings used by iterator support
        self._pid = None
        signal.signal(signal.SIGINT, self._kill_pipe)
        self._results_iter = iter(self._results_q.get, None)
        self._results = deque()

        if pkg_scan:
            # package level scans sort all returned results
            self._ordered_results = {
                scope: [] for scope in base.scopes.values()
                if scope >= base.package_scope
            }
        else:
            # scoped mapping for caching repo and location specific results
            self._ordered_results = {
                scope: [] for scope in reversed(list(base.scopes.values()))
                if scope <= base.repo_scope
            }

    def _filter_checks(self, scan_scope, checks):
        """Verify check scope against current scan scope to determine check activation."""
        for check in checks:
            if isinstance(check.scope, base.ConditionalScope):
                # conditionally enabled check
                yield check
            elif isinstance(check.scope, base.LocationScope):
                if not self.options.selected_scopes:
                    if scan_scope == base.repo_scope or check.scope in scan_scope:
                        # allow repo scans or cwd scope to trigger location specific checks
                        yield check
                elif check.scope in self.options.selected_scopes:
                    # Allow checks with special scopes to be run when specifically
                    # requested, e.g. eclass-only scanning.
                    yield check
            elif isinstance(scan_scope, base.PackageScope) and check.scope >= scan_scope:
                # Only run pkg-related checks at or below the current scan scope level, if
                # pkg scanning is requested, e.g. skip repo level checks when scanning at
                # package level.
                yield check

    def _create_runners(self, scan_scope, pkg_scan):
        """Initialize and categorize checkrunners for results pipeline."""
        # filter enabled checks based on the scanning scope
        enabled_checks = list(self._filter_checks(scan_scope, self.options.enabled_checks))
        if not enabled_checks:
            raise base.PkgcheckUserException(
                f'no matching checks available for {scan_scope} scope')

        # initialize enabled checks
        addons = base.get_addons(enabled_checks)
        enabled_checks = init_checks(addons, self.options, self._results_q)

        # Initialize checkrunners per source type using separate runner for
        # async checks and categorize them for parallelization based on the
        # scan and source scope.
        runner_cls = {'async': AsyncCheckRunner, 'sync': SyncCheckRunner}
        pipes = {'sync': defaultdict(list), 'async': defaultdict(list)}
        for (source, exec_type), checks in enabled_checks.items():
            runner = runner_cls[exec_type](self.options, source, checks)
            if not pkg_scan and source.scope >= base.package_scope:
                pipes[exec_type][base.package_scope].append(runner)
            else:
                pipes[exec_type][source.scope].append(runner)

        return pipes

    def _kill_pipe(self, *args, error=None):
        """Handle terminating the pipeline process group."""
        if self._pid is not None:
            os.killpg(self._pid, signal.SIGKILL)
        if error is not None:
            # propagate exception raised during parallel scan
            raise base.PkgcheckUserException(error)
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
                    if self._ordered_results is None:
                        raise
                    self._pid = None
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

    def _queue_work(self, sync_pipes, work_q, restrictions):
        """Producer that queues scanning tasks against granular scope restrictions."""
        for restriction in restrictions:
            for scope in sorted(sync_pipes, reverse=True):
                pipes = sync_pipes[scope]
                if scope == base.version_scope:
                    versioned_source = VersionedSource(self.options)
                    for restrict in versioned_source.itermatch(restriction):
                        for i in range(len(pipes)):
                            work_q.put((scope, restrict, i))
                elif scope == base.package_scope:
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

                if scope == base.version_scope:
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
                    self._results_q.put(sorted(results))
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
        self.checks = sorted(checks)


class SyncCheckRunner(CheckRunner):
    """Generic runner for synchronous checks."""

    def __init__(self, *args):
        super().__init__(*args)
        # set of known results for all checks run by the checkrunner
        self._known_results = set().union(*(x.known_results for x in self.checks))
        # used to store MetadataError results for processing
        self._metadata_errors = deque()

        # only report metadata errors for version-scoped sources
        if self.source.scope == base.version_scope:
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
        result_cls = MetadataError.results[e.attr]
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
