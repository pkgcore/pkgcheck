"""Core classes and interfaces.

This defines a couple of standard feed types and scopes. Currently
feed types are strings and scopes are integers, but you should use the
symbolic names wherever possible (everywhere except for adding a new
feed type) since this might change in the future. Scopes are integers,
but do not rely on that either.

Feed types have to match exactly. Scopes are ordered: they define a
minimally accepted scope, and for transforms the output scope is
identical to the input scope.
"""

import re
import sys
from collections import OrderedDict, defaultdict, namedtuple
from contextlib import AbstractContextManager
from operator import attrgetter, itemgetter

from pkgcore import const as pkgcore_const
from pkgcore.config.hint import ConfigHint
from pkgcore.ebuild import cpv
from pkgcore.package.errors import MetadataException
from pkgcore.restrictions import util
from snakeoil.decorators import coroutine
from snakeoil.klass import jit_attr
from snakeoil.osutils import pjoin

from .log import logger

# source feed types
commit_feed = 'git'
repository_feed = 'repo'
category_feed = 'cat'
package_feed = 'cat/pkg'
raw_package_feed = '(cat, pkg)'
versioned_feed = 'cat/pkg-ver'
raw_versioned_feed = '(cat, pkg, ver)'
ebuild_feed = 'cat/pkg-ver+text'

# mapping for -S/--scopes option, ordered for sorted output in the case of unknown scopes
_Scope = namedtuple('Scope', ['threshold', 'desc'])
known_scopes = OrderedDict((
    ('git', _Scope(commit_feed, 'commit')),
    ('repo', _Scope(repository_feed, 'repository')),
    ('cat', _Scope(category_feed, 'category')),
    ('pkg', _Scope(package_feed, 'package')),
    ('ver', _Scope(versioned_feed, 'version')),
))

# The plugger needs to be able to compare scopes.
for i, scope in enumerate(reversed(known_scopes.values())):
    globals()[f'{scope.desc}_scope'] = i

CACHE_DIR = pjoin(pkgcore_const.USER_CACHE_PATH, 'pkgcheck')


class Addon:
    """Base class for extra functionality for pkgcheck other than a check.

    The checkers can depend on one or more of these. They will get
    called at various points where they can extend pkgcheck (if any
    active checks depend on the addon).

    These methods are not part of the checker interface because that
    would mean addon functionality shared by checkers would run twice.
    They are not plugins because they do not do anything useful if no
    checker depending on them is active.

    This interface is not finished. Expect it to grow more methods
    (but if not overridden they will be no-ops).

    :cvar required_addons: sequence of addons this one depends on.
    """

    required_addons = ()

    def __init__(self, options, *args):
        """Initialize.

        An instance of every addon in required_addons is passed as extra arg.

        :param options: the argparse values.
        """
        self.options = options

    @staticmethod
    def mangle_argparser(parser):
        """Add extra options and/or groups to the argparser.

        This hook is always triggered, even if the checker is not
        activated (because it runs before the commandline is parsed).

        :param parser: an C{argparse.ArgumentParser} instance.
        """

    @staticmethod
    def check_args(parser, namespace):
        """Postprocess the argparse values.

        Should raise C{argparse.ArgumentError} on failure.

        This is only called for addons that are enabled, but before
        they are instantiated.
        """


class GenericSource:
    """Base template for a repository source."""

    required_addons = ()
    feed_type = versioned_feed
    cost = 10

    def __init__(self, options):
        self.options = options
        self.repo = options.target_repo

    def itermatch(self, restrict, **kwargs):
        yield from self.repo.itermatch(restrict, sorter=sorted, **kwargs)


class EmptySource(GenericSource):
    """Empty source meant for skipping feed."""

    def itermatch(self, restrict):
        yield from ()


class Feed(Addon):
    """Base template for addon iterating over an item feed.

    :cvar scope: scope relative to the package repository the check runs under
    :cvar priority: priority level of the check which plugger sorts by --
        should be left alone except for weird pseudo-checks like the cache
        wiper that influence other checks
    :cvar source: source of feed items
    """

    scope = version_scope
    priority = 0
    source = GenericSource

    def start(self):
        """Do startup here."""

    def feed(self, item):
        raise NotImplementedError

    def finish(self):
        """Do cleanup and omit final results here."""


class EmptyFeed(Feed):
    """Empty feed that skips the object feeding phase."""

    source = EmptySource

    # required for tests since they manually run the checks instead of
    # constructing pipelines
    def feed(self, item):
        pass


class Check(Feed):
    """Base template for a check.

    :cvar scope: scope relative to the package repository the check runs under
    :cvar source: source of feed items
    :cvar known_results: result keywords the check can possibly yield
    """

    known_results = ()

    @classmethod
    def skip(cls, namespace):
        """Conditionally skip check when running all enabled checks."""
        return False


class GentooRepoCheck(Check):
    """Check that is only valid when run against the gentoo repo."""

    @classmethod
    def skip(cls, namespace):
        skip = not namespace.gentoo_repo
        if skip:
            logger.info(f'skipping {cls.__name__}, not running against gentoo repo')
        return skip or super().skip(namespace)


class OverlayRepoCheck(Check):
    """Check that is only valid when run against an overlay repo."""

    @classmethod
    def skip(cls, namespace):
        skip = not namespace.target_repo.masters
        if skip:
            logger.info(f'skipping {cls.__name__}, not running against overlay repo')
        return skip or super().skip(namespace)


class ExplicitlyEnabledCheck(Check):
    """Check that is only valid when explicitly enabled."""

    @classmethod
    def skip(cls, namespace):
        if namespace.selected_checks is not None:
            disabled, enabled = namespace.selected_checks
        else:
            disabled, enabled = [], []

        # enable checks for selected keywords
        keywords = namespace.filtered_keywords
        if keywords is not None:
            keywords = keywords.intersection(cls.known_results)

        enabled += namespace.forced_checks
        skip = cls.__name__ not in enabled and not keywords
        if skip:
            logger.info(f'skipping {cls.__name__}, not explicitly enabled')
        return skip or super().skip(namespace)


class Transform:
    """Base class for a feed type transformer.

    :cvar source: start type
    :cvar dest: destination type
    :cvar scope: minimum scope
    :cvar cost: cost
    """

    def __init__(self, child):
        self.child = child

    def start(self):
        """Startup."""
        yield from self.child.start()

    def feed(self, item):
        raise NotImplementedError

    def finish(self):
        """Clean up."""
        yield from self.child.finish()

    def __repr__(self):
        return f'{self.__class__.__name__}({self.child!r})'


class Result:

    # level values match those used in logging module
    _level = 20
    _level_to_desc = {
        40: ('error', 'red'),
        30: ('warning', 'yellow'),
        20: ('info', 'green'),
    }

    @property
    def color(self):
        return self._level_to_desc[self._level][1]

    @property
    def level(self):
        return self._level_to_desc[self._level][0]

    def __str__(self):
        return self.desc

    @property
    def desc(self):
        raise NotImplementedError

    @property
    def _attrs(self):
        return {k: v for k, v in self.__dict__.items() if not k.startswith('_')}

    def __eq__(self, other):
        return self._attrs == other._attrs

    def __hash__(self):
        return hash(tuple(sorted(self._attrs)))

    def __lt__(self, other):
        return self.__class__.__name__ < other.__class__.__name__


class Error(Result):
    """Result with an error priority level."""

    _level = 40


class Warning(Result):
    """Result with a warning priority level."""

    _level = 30


class Info(Result):
    """Result with an info priority level."""

    _level = 20


class CommitResult(Result):
    """Result related to a specific git commit."""

    threshold = commit_feed

    def __init__(self, commit, **kwargs):
        super().__init__(**kwargs)
        self.commit = commit.commit
        self._attr = 'commit'


class CategoryResult(Result):
    """Result related to a specific category."""

    threshold = category_feed

    def __init__(self, pkg, **kwargs):
        super().__init__(**kwargs)
        self.category = pkg.category
        self._attr = 'category'

    def __lt__(self, other):
        if self.category < other.category:
            return True
        return super().__lt__(other)


class PackageResult(CategoryResult):
    """Result related to a specific package."""

    threshold = package_feed

    def __init__(self, pkg, **kwargs):
        super().__init__(pkg, **kwargs)
        self.package = pkg.package
        self._attr = 'package'

    def __lt__(self, other):
        if self.package < other.package:
            return True
        return super().__lt__(other)


class VersionedResult(PackageResult):
    """Result related to a specific version of a package."""

    threshold = versioned_feed

    def __init__(self, pkg, **kwargs):
        super().__init__(pkg, **kwargs)
        self.version = pkg.fullver
        self._attr = 'version'

    @jit_attr
    def ver_rev(self):
        version, _, revision = self.version.partition('-r')
        revision = cpv._Revision(revision)
        return version, revision

    def __lt__(self, other):
        cmp = cpv.ver_cmp(*(self.ver_rev + other.ver_rev))
        if cmp < 0:
            return True
        elif cmp > 0:
            return False
        return super().__lt__(other)


class LogError(Error):
    """Error caught from a logger instance."""

    def __init__(self, msg):
        super().__init__()
        self.msg = msg

    @property
    def desc(self):
        return self.msg


class LogWarning(Warning, LogError):
    """Warning caught from a logger instance."""


class MetadataError(VersionedResult, Error):
    """Problem detected with a package's metadata."""

    def __init__(self, attr, msg, **kwargs):
        super().__init__(**kwargs)
        self.attr = attr
        self.msg = str(msg)

    @property
    def desc(self):
        return f"attr({self.attr}): {self.msg}"


class Reporter:
    """Generic result reporter."""

    def __init__(self, out, keywords=None):
        """Initialize

        :type out: L{snakeoil.formatters.Formatter}
        :param keywords: result keywords to report, other keywords will be skipped
        """
        self.out = out
        self._filtered_keywords = set(keywords) if keywords is not None else keywords

        # initialize result processing coroutines
        self.report = self._add_report().send
        self.process = self._process_report().send

    @coroutine
    def _add_report(self):
        """Add a report result to be processed for output."""
        # only process reports for keywords that are enabled
        while True:
            result = (yield)
            if self._filtered_keywords is None or result.__class__ in self._filtered_keywords:
                self.process(result)

    @coroutine
    def _process_report(self):
        """Render and output a report result.."""
        raise NotImplementedError(self._process_report)

    def start(self):
        """Initialize reporter output."""

    def finish(self):
        """Finalize reporter output."""


def convert_check_filter(tok):
    """Convert an input string into a filter function.

    The filter function accepts a qualified python identifier string
    and returns a bool.

    The input can be a regexp or a simple string. A simple string must
    match a component of the qualified name exactly. A regexp is
    matched against the entire qualified name.

    Matches are case-insensitive.

    Examples::

      convert_check_filter('foo')('a.foo.b') == True
      convert_check_filter('foo')('a.foobar') == False
      convert_check_filter('foo.*')('a.foobar') == False
      convert_check_filter('foo.*')('foobar') == True
    """
    tok = tok.lower()
    if '+' in tok or '*' in tok:
        return re.compile(tok, re.I).match
    else:
        toklist = tok.split('.')

        def func(name):
            chunks = name.lower().split('.')
            if len(toklist) > len(chunks):
                return False
            for i in range(len(chunks)):
                if chunks[i:i + len(toklist)] == toklist:
                    return True
            return False

        return func


class _CheckSet:
    """Run only listed checks."""

    # No config hint here since this one is abstract.

    def __init__(self, patterns):
        self.patterns = list(convert_check_filter(pat) for pat in patterns)


class Whitelist(_CheckSet):
    """Only run checks matching one of the provided patterns."""

    pkgcore_config_type = ConfigHint(
        {'patterns': 'list'}, typename='pkgcheck_checkset')

    def filter(self, checks):
        return list(
            c for c in checks
            if any(p(f'{c.__module__}.{c.__name__}') for p in self.patterns))


class Blacklist(_CheckSet):
    """Only run checks not matching any of the provided patterns."""

    pkgcore_config_type = ConfigHint(
        {'patterns': 'list'}, typename='pkgcheck_checkset')

    def filter(self, checks):
        return list(
            c for c in checks
            if not any(p(f'{c.__module__}.{c.__name__}') for p in self.patterns))


def filter_update(objs, enabled=(), disabled=()):
    """Filter a given list of check or result types."""
    if enabled:
        whitelist = Whitelist(enabled)
        objs = list(whitelist.filter(objs))
    if disabled:
        blacklist = Blacklist(disabled)
        objs = list(blacklist.filter(objs))
    return objs


class Scope:
    """Only run checks matching any of the given scopes."""

    pkgcore_config_type = ConfigHint(
        {'scopes': 'list'}, typename='pkgcheck_checkset')

    def __init__(self, scopes):
        self.scopes = tuple(int(x) for x in scopes)

    def filter(self, checks):
        return list(c for c in checks if c.scope in self.scopes)


class ProgressManager(AbstractContextManager):
    """Context manager for handling progressive output.

    Useful for updating the user about the status of a long running process.
    """

    def __init__(self, debug=False):
        self.debug = debug
        self._triggered = False

    def _progress_callback(self, s):
        """Callback used for progressive output."""
        sys.stderr.write(f'{s}\r')
        self._triggered = True

    def __enter__(self):
        if self.debug:
            return self._progress_callback
        else:
            return lambda x: None

    def __exit__(self, _exc_type, _exc_value, _traceback):
        if self._triggered:
            sys.stderr.write('\n')


class RawCPV:
    """Raw CPV objects supporting basic restrictions/sorting."""

    __slots__ = ('category', 'package', 'fullver')

    def __init__(self, category, package, fullver):
        self.category = category
        self.package = package
        self.fullver = fullver

    def __str__(self):
        return f'{self.category}/{self.package}-{self.fullver}'

    def __lt__(self, other):
        if self.category < other.category:
            return True
        if self.package < other.package:
            return True
        if self.fullver < other.fullver:
            return True
        return False


class InterleavedSources:
    """Iterate over multiple sources, interleaving them in sorted fashion."""

    def __init__(self, sources):
        self.sources = sources
        self._cache = {}

    def __iter__(self):
        return self

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

        l = sorted(self._cache.items(), key=itemgetter(1))
        pipe_idx, item = l[0]
        del self._cache[pipe_idx]
        return item, pipe_idx


class GitPipeline:

    def __init__(self, checks, source):
        self.checkrunner = CheckRunner(checks)
        self.source = source

    def run(self):
        yield from self.checkrunner.start()
        for commit in self.source:
            yield from self.checkrunner.feed(commit)
        yield from self.checkrunner.finish()


class Pipeline:

    def __init__(self, pipes, restrict):
        sources = [(source.itermatch(restrict), i) for i, (source, pipe) in enumerate(pipes)]
        self.interleaved = InterleavedSources(sources)
        self.pipes = tuple(x[1] for x in pipes)

    def run(self):
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
        return (self.__class__ is other.__class__ and
            frozenset(self.checks) == frozenset(other.checks))

    def __ne__(self, other):
        return not self == other

    def __hash__(self):
        return hash(frozenset(self.checks))

    def __repr__(self):
        checks = ', '.join(sorted(str(check) for check in self.checks))
        return f'{self.__class__.__name__}({checks})'


def plug(sinks, transforms, sources, scan_scope=repository_scope, debug=None):
    """Plug together a pipeline.

    This tries to return a single pipeline if possible (even if it is
    more "expensive" than using separate pipelines). If more than one
    pipeline is needed it does not try to minimize the number.

    :param sinks: Sequence of check instances.
    :param transforms: Sequence of transform classes.
    :param sources: Dict of raw sources to source instances.
    :param scan_scope: Scope at which the current scan is running.
    :param debug: A logging function or C{None}.
    :return: a sequence of sinks that are unreachable (out of scope or
        missing sources/transforms of the right type),
        a sequence of (source, consumer) tuples.
    """

    # This is not optimized to deal with huge numbers of sinks,
    # sources and transforms, but that should not matter (although it
    # may be necessary to handle a lot of sinks a bit better at some
    # point, which should be fairly easy since we only care about
    # their type and scope).

    feed_to_transforms = defaultdict(list)
    for transform in transforms:
        feed_to_transforms[transform.source].append(transform)

    # Map from typename to best scope
    best_scope = {}
    for source in sources.values():
        # (not particularly clever, if we get a ton of sources this
        # should be optimized to do less duplicate work).
        reachable = set()
        todo = set([source.feed_type])
        while todo:
            feed_type = todo.pop()
            reachable.add(feed_type)
            for transform in feed_to_transforms.get(feed_type, ()):
                if (transform.scope <= scan_scope and transform.dest not in reachable):
                    todo.add(transform.dest)
        for feed_type in reachable:
            scope = best_scope.get(feed_type)
            if scope is None or scope < scan_scope:
                best_scope[feed_type] = scan_scope

    # Throw out unreachable sinks.
    good_sinks = []
    bad_sinks = []
    for sink in sinks:
        scope = best_scope.get(sink.feed_type)
        if scope is None or sink.scope > scope:
            bad_sinks.append(sink)
        else:
            good_sinks.append(sink)

    if not good_sinks:
        # No point in continuing.
        return bad_sinks, ()

    # all feed types we need to reach for each source type
    sink_feed_map = defaultdict(set)
    for sink in good_sinks:
        sink_feed_map[sink.source].add(sink.feed_type)

    # tuples of (visited_types, source, transforms, price)
    unprocessed = set(
        (frozenset((source.feed_type,)), raw, source, frozenset(), source.cost)
        for raw, source in sources.items())
    if debug is not None:
        for pipe in unprocessed:
            debug(f'initial: {pipe!r}')

    # If we find a single pipeline driving all sinks we want to use it.
    # List of tuples of source, transforms.
    pipes = set()
    pipes_to_run = []
    best_cost = None
    required_source_costs = {}
    while unprocessed:
        pipe = unprocessed.pop()
        if pipe in pipes:
            continue
        pipes.add(pipe)
        visited, raw, source, trans, cost = pipe
        best_cost = required_source_costs.get(raw, None)
        if visited >= sink_feed_map[raw]:
            # Already reaches all sink types. Check if it is usable as
            # single pipeline:
            if best_cost is None or cost < best_cost:
                pipes_to_run.append((raw, source, trans))
                required_source_costs[raw] = cost
                best_cost = cost
            # No point in growing this further: it already reaches everything.
            continue
        if best_cost is not None and best_cost <= cost:
            # No point in growing this further.
            continue
        for transform in transforms:
            if (getattr(source, 'scope', scan_scope) >= transform.scope and
                    transform.source in visited and
                    transform.dest not in visited):
                unprocessed.add((
                    visited.union((transform.dest,)), raw, source,
                    trans.union((transform,)), cost + transform.cost))
                if debug is not None:
                    debug(f'growing {trans!r} for {source!r} with {transform!r}')

    # Just an assert since unreachable sinks should have been thrown away.
    assert pipes_to_run, 'did not find a solution?'

    good_sinks.sort(key=attrgetter('priority'))

    def build_transform(scope, feed_type, source_type, transforms):
        children = []
        for transform in transforms:
            if transform.source == feed_type and transform.scope <= scope:
                # Note this relies on the cheapest pipe not having any "loops"
                # in its transforms.
                t = build_transform(scope, transform.dest, source_type, transforms)
                if t:
                    children.append(transform(t))
        # Hacky: we modify this in place.
        for i in reversed(range(len(good_sinks))):
            sink = good_sinks[i]
            if (sink.feed_type == feed_type and
                    sink.source == source_type and sink.scope <= scope):
                children.append(sink)
                del good_sinks[i]
        if children:
            return CheckRunner(children)

    result = []
    for source_type, source, transforms in pipes_to_run:
        transform = build_transform(
            getattr(source, 'scope', scan_scope), source.feed_type, source_type, transforms)
        if transform:
            result.append((source, transform))

    assert not good_sinks, f'sinks left: {good_sinks!r}'
    return bad_sinks, result
