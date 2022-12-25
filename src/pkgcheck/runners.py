"""Check runners."""

from collections import deque
from functools import partial

from pkgcore.package.errors import MetadataException
from pkgcore.restrictions import packages

from . import base
from .results import MetadataError


class CheckRunner:
    """Generic runner for checks.

    Checks are run in order of priority. Some checks need to be run before
    others if both are enabled due to package attribute caching in pkgcore,
    e.g. checks that test depset parsing need to come before other checks that
    use the parsed deps otherwise results from parsing errors could be missed.
    """

    # check type classification to support checkrunner initialization
    type = None

    def __init__(self, options, source, checks):
        self.options = options
        self.source = source
        self.checks = sorted(checks)


class SyncCheckRunner(CheckRunner):
    """Generic runner for synchronous checks."""

    type = "sync"

    def __init__(self, *args):
        super().__init__(*args)
        # set of known results for all checks run by the checkrunner
        self._known_results = set().union(*(x.known_results for x in self.checks))
        # used to store MetadataError results for processing
        self._metadata_errors = deque()

        # only report metadata errors for version-scoped sources
        if self.source.scope == base.version_scope:
            self.source.itermatch = partial(
                self.source.itermatch, error_callback=self._metadata_error_cb
            )

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
            error_str = ": ".join(e.msg().split("\n"))
            result = result_cls(e.attr, error_str, pkg=e.pkg)
            self._metadata_errors.append((e.pkg, result))

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

        for check in self.checks:
            check.cleanup()


class RepoCheckRunner(SyncCheckRunner):
    """Generic runner for checks run across an entire repo."""

    def run(self, *args):
        for check in self.checks:
            check.start()
        yield from super().run(*args)
        for check in self.checks:
            yield from check.finish()


class SequentialCheckRunner(SyncCheckRunner):
    """Generic runner for sequential checks.

    Checks that must not be run in parallel, will be run on the main process.
    """

    type = "sequential"


class AsyncCheckRunner(CheckRunner):
    """Generic runner for asynchronous checks.

    Checks that would otherwise block for uncertain amounts of time due to I/O
    or network access are run in separate threads, queuing any relevant results
    on completion.
    """

    type = "async"

    def schedule(self, executor, futures, restrict=packages.AlwaysTrue):
        """Schedule all checks to run via the given executor."""
        for item in self.source.itermatch(restrict):
            for check in self.checks:
                check.schedule(item, executor, futures)
