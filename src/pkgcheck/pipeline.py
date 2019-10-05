"""Pipeline building support for connecting sources and checks."""

import concurrent.futures
import os
from collections import defaultdict, deque
from itertools import chain
from multiprocessing import Pool, Process, SimpleQueue

from pkgcore.package.errors import MetadataException
from pkgcore.restrictions import packages

from . import base
from .results import MetadataError
from .sources import UnversionedSource, VersionedSource


class GitPipeline:

    def __init__(self, source, checks):
        self.checkrunner = CheckRunner(source, checks)

    def __iter__(self):
        yield from self.checkrunner.start()
        yield from self.checkrunner.run()
        yield from self.checkrunner.finish()


class Pipeline:

    def __init__(self, options, scan_scope, pipes, restrict):
        self.options = options
        self.scan_scope = scan_scope
        self.pipes = pipes
        self.restrict = restrict
        self.jobs = options.jobs

    def _queue_work(self, scoped_pipes, async_pipes, work_q):
        # queue restriction tasks based on scope for check running parallelism
        for scope, pipes in scoped_pipes.items():
            if scope == base.version_scope:
                versioned_source = VersionedSource(self.options)
                for restrict in versioned_source.itermatch(self.restrict):
                    for i in range(len(pipes)):
                        work_q.put((scope, restrict, i))
            elif scope == base.package_scope:
                unversioned_source = UnversionedSource(self.options)
                for restrict in unversioned_source.itermatch(self.restrict):
                    work_q.put((scope, restrict, 0))
            else:
                work_q.put((scope, self.restrict, 0))

        # insert flags to notify processes that no more work exists
        for i in range(self.jobs):
            work_q.put((None, None, None))

        # run all async checks from a single process
        for scope, pipes in async_pipes.items():
            for pipe in pipes:
                pipe.run(self.restrict)

    def _run_checks(self, sync_pipes, work_q, results_q):
        while True:
            scope, restrict, check_idx = work_q.get()
            if scope is None:
                return
            if scope == base.version_scope:
                results_q.put(list(sync_pipes[scope][check_idx].run(restrict)))
            else:
                results = []
                for pipe in sync_pipes[scope]:
                    if scope == base.repository_scope:
                        results.extend(pipe.start())
                    results.extend(pipe.run(restrict))
                    if scope == base.repository_scope:
                        results.extend(pipe.finish())
                results_q.put(results)

    def run(self, results_q):
        # initialize checkrunners per source type, using separate runner for async checks
        checkrunners = defaultdict(list)
        for pipe_mapping in self.pipes:
            for (source, is_async), checks in pipe_mapping.items():
                if is_async:
                    runner = AsyncCheckRunner(source, checks, results_q=results_q)
                else:
                    runner = CheckRunner(source, checks)
                checkrunners[(source.feed_type, is_async)].append(runner)

        # categorize checkrunners for parallelization based on the scan and source scope
        scoped_pipes = defaultdict(lambda: defaultdict(list))
        if self.scan_scope == base.version_scope:
            for (scope, is_async), runners in checkrunners.items():
                scoped_pipes[is_async][base.version_scope].extend(runners)
        elif self.scan_scope == base.package_scope:
            for (scope, is_async), runners in checkrunners.items():
                if scope == base.version_scope:
                    scoped_pipes[is_async][base.version_scope].extend(runners)
                else:
                    scoped_pipes[is_async][base.package_scope].extend(runners)
        else:
            for (scope, is_async), runners in checkrunners.items():
                if scope <= base.package_scope:
                    scoped_pipes[is_async][base.package_scope].extend(runners)
                else:
                    scoped_pipes[is_async][scope].extend(runners)

        sync_pipes = scoped_pipes[False]
        async_pipes = scoped_pipes[True]
        work_q = SimpleQueue()

        # split target restriction into tasks for parallelization
        p = Process(target=self._queue_work, args=(sync_pipes, async_pipes, work_q))
        p.start()
        # run tasks using process pool, queuing generated results for reporting
        pool = Pool(self.jobs, self._run_checks, (sync_pipes, work_q, results_q))
        pool.close()
        p.join()
        pool.join()

        results_q.put(None)


class CheckRunner:

    _known_metadata_attrs = set()
    _seen_metadata_errors = set()

    def __init__(self, source, checks):
        self.source = source
        self.checks = checks

        scope = base.version_scope
        known_results = set()
        for check in self.checks:
            if check.scope > scope:
                scope = check.scope
            known_results.update(check.known_results)

        self._itermatch_kwargs = {}
        # only use set metadata error callback for version scope runners
        if scope == base.version_scope:
            self._itermatch_kwargs['error_callback'] = self._metadata_error_cb

        self._metadata_error_classes = {}
        for cls in known_results:
            if issubclass(cls, MetadataError):
                for attr in cls._metadata_attrs:
                    self._metadata_error_classes[attr] = cls
                    self._known_metadata_attrs.add(attr)
        self._metadata_errors = deque()

    def _metadata_error_cb(self, e):
        try:
            cls = self._metadata_error_classes[e.attr]
        except KeyError:
            known = e.attr in self._known_metadata_attrs
            seen = e in self._seen_metadata_errors
            # return generic MetadataError for unhandled attributes that
            # haven't been seen already
            if not known and not seen:
                cls = MetadataError
                self._seen_metadata_errors.add(e)
            else:
                cls = None

        if cls is not None:
            error_str = ': '.join(e.msg().split('\n'))
            result = cls(e.attr, error_str, pkg=e.pkg)
            self._metadata_errors.append((e.pkg, result))

    def start(self):
        for check in self.checks:
            reports = check.start()
            if reports is not None:
                yield from reports

    def run(self, restrict=packages.AlwaysTrue):
        try:
            source = self.source.itermatch(restrict, **self._itermatch_kwargs)
        except AttributeError:
            source = self.source

        for item in source:
            for check in self.checks:
                try:
                    reports = check.feed(item)
                    if reports is not None:
                        yield from reports
                except MetadataException as e:
                    self._metadata_error_cb(e)

        while self._metadata_errors:
            pkg, result = self._metadata_errors.popleft()
            # Only show metadata errors for packages matching the current
            # restriction to avoid duplicate reports.
            if restrict.match(pkg):
                yield result

    def finish(self):
        for check in self.checks:
            reports = check.finish()
            if reports is not None:
                yield from reports

    # The plugger tests use these.
    def __eq__(self, other):
        return (
            self.__class__ is other.__class__ and
            frozenset(self.checks) == frozenset(other.checks))

    def __ne__(self, other):
        return not self == other

    def __hash__(self):
        return hash(frozenset(self.checks))

    def __repr__(self):
        checks = ', '.join(sorted(str(check) for check in self.checks))
        return f'{self.__class__.__name__}({checks})'


class AsyncCheckRunner(CheckRunner):

    def __init__(self, *args, results_q, **kwargs):
        super().__init__(*args, **kwargs)
        self.results_q = results_q

    def run(self, restrict=packages.AlwaysTrue):
        try:
            source = self.source.itermatch(restrict, **self._itermatch_kwargs)
        except AttributeError:
            source = self.source

        with concurrent.futures.ThreadPoolExecutor() as executor:
            futures = {}
            for item in source:
                for check in self.checks:
                    check.schedule(item, executor, futures, self.results_q)
