"""Pipeline building support for connecting sources and checks."""

from pkgcore.package.errors import MetadataException

from .results import MetadataError


class InterleavedSources:
    """Iterate over multiple sources, interleaving them in sorted fashion."""

    def __init__(self, sources):
        self.sources = sources
        self._cache = {}

    def __iter__(self):
        return self

    def _key(self, obj):
        obj = obj[1]
        if isinstance(obj, list):
            return obj[0]
        return obj

    def __next__(self):
        if not self.sources:
            raise StopIteration

        if len(self.sources) == 1:
            source, pipe_idx = self.sources[0]
            return next(source), pipe_idx

        i = 0
        while i < len(self.sources):
            source, pipe_idx = self.sources[i]
            try:
                self._cache[pipe_idx]
            except KeyError:
                try:
                    self._cache[pipe_idx] = next(source)
                except StopIteration:
                    self.sources.pop(i)
                    continue
            i += 1

        if not self._cache:
            raise StopIteration

        l = sorted(self._cache.items(), key=self._key)
        pipe_idx, item = l[0]
        del self._cache[pipe_idx]
        return item, pipe_idx


class GitPipeline:

    def __init__(self, checks, source):
        self.checkrunner = CheckRunner(checks)
        self.source = source

    def __iter__(self):
        yield from self.checkrunner.start()
        for commit in self.source:
            yield from self.checkrunner.feed(commit)
        yield from self.checkrunner.finish()


class Pipeline:

    def __init__(self, pipes, restrict):
        sources = [(source.itermatch(restrict), i) for i, (source, pipe) in enumerate(pipes)]
        self.interleaved = InterleavedSources(sources)
        self.pipes = tuple(x[1] for x in pipes)

    def __iter__(self):
        for pipe in self.pipes:
            yield from pipe.start()
        for item, i in self.interleaved:
            yield from self.pipes[i].feed(item)
        for pipe in self.pipes:
            yield from pipe.finish()


class CheckRunner:

    def __init__(self, checks):
        self.checks = checks
        self._metadata_errors = set()

    def start(self):
        for check in self.checks:
            try:
                reports = check.start()
                if reports is not None:
                    yield from reports
            except MetadataException as e:
                exc_info = (e.pkg, e.error)
                # only report distinct metadata errors
                if exc_info not in self._metadata_errors:
                    self._metadata_errors.add(exc_info)
                    error_str = ': '.join(str(e.error).split('\n'))
                    yield MetadataError(e.attr, error_str, pkg=e.pkg)

    def feed(self, item):
        for check in self.checks:
            try:
                reports = check.feed(item)
                if reports is not None:
                    yield from reports
            except MetadataException as e:
                exc_info = (e.pkg, e.error)
                # only report distinct metadata errors
                if exc_info not in self._metadata_errors:
                    self._metadata_errors.add(exc_info)
                    error_str = ': '.join(str(e.error).split('\n'))
                    yield MetadataError(e.attr, error_str, pkg=e.pkg)

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


def plug(pipes):
    """Plug together a pipeline.

    :param pipes: Iterable of source -> check pipe mappings.
    :return: A generator of (source, consumer) tuples.
    """
    for pipe_mapping in pipes:
        for source, checks in pipe_mapping.items():
            yield source, CheckRunner(checks)
