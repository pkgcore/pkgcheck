"""Core classes and interfaces.

This defines a couple of standard feed types and scopes. Currently
feed types are strings and scopes are integers, but you should use the
symbolic names wherever possible (everywhere except for adding a new
feed type) since this might change in the future. Scopes are integers,
but do not rely on that either.

Feed types have to match exactly. Scopes are ordered: they define a
minimally accepted scope.
"""

import re
import sys
from collections import OrderedDict, defaultdict, namedtuple, deque
from contextlib import AbstractContextManager

from pkgcore import const as pkgcore_const
from pkgcore.config.hint import ConfigHint
from pkgcore.ebuild import atom, cpv
from pkgcore.package.errors import MetadataException
from pkgcore.restrictions import util
from snakeoil import klass
from snakeoil.decorators import coroutine
from snakeoil.osutils import pjoin

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


class Reporter:
    """Generic result reporter."""

    def __init__(self, out, verbosity=0, keywords=None):
        """Initialize

        :type out: L{snakeoil.formatters.Formatter}
        :param keywords: result keywords to report, other keywords will be skipped
        """
        self.out = out
        self.verbosity = verbosity
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
                # skip filtered results by default
                if self.verbosity < 1 and result._filtered:
                    continue
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

    def __lt__(self, other):
        if self.versioned_atom < other.versioned_atom:
            return True
        return False

    @property
    def key(self):
        return f'{self.category}/{self.package}'

    @property
    def versioned_atom(self):
        if self.fullver:
            return atom.atom(f'={self}')
        return atom.atom(str(self))

    def __str__(self):
        if self.fullver:
            return f'{self.category}/{self.package}-{self.fullver}'
        return f'{self.category}/{self.package}'

    def __repr__(self):
        address = '@%#8x' % (id(self),)
        return f'<{self.__class__} cpv={self.versioned_atom.cpvstr!r} {address}>'


class WrappedPkg:
    """Generic package wrapper used to inject attributes into package objects."""

    __slots__ = ('_pkg',)

    def __init__(self, pkg):
        self._pkg = pkg

    def __str__(self):
        return str(self._pkg)

    def __repr__(self):
        return repr(self._pkg)

    def __lt__(self, other):
        if self.versioned_atom < other.versioned_atom:
            return True
        return False

    __getattr__ = klass.GetAttrProxy('_pkg')
    __dir__ = klass.DirProxy('_pkg')


class FilteredPkg(WrappedPkg):
    """Filtered package used to mark related results that should be skipped by default."""


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


def plug(checks, sources):
    """Plug together a pipeline.

    This tries to return a single pipeline if possible (even if it is
    more "expensive" than using separate pipelines). If more than one
    pipeline is needed it does not try to minimize the number.

    :param checks: Sequence of check instances.
    :param sources: Dict of raw sources to source instances.
    :return: A sequence of (source, consumer) tuples.
    """
    sinks = list(checks)

    def build_sink(source_type):
        children = []
        # Hacky: we modify this in place.
        for i in reversed(range(len(sinks))):
            sink = sinks[i]
            if sink.source == source_type:
                children.append(sink)
                del sinks[i]
        if children:
            return CheckRunner(children)

    good_sinks = []
    for source_type, source, in sources.items():
        sink = build_sink(source_type)
        if sink:
            good_sinks.append((source, sink))

    assert not sinks, f'sinks left: {sinks!r}'
    return good_sinks
