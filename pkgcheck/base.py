# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# Copyright: 2006 Marien Zwart <marienz@gentoo.org>
# License: BSD/GPL2

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

from operator import attrgetter

from pkgcore.config import ConfigHint
from snakeoil.demandload import demandload

demandload(
    'itertools',
    'logging',
    're',
)

repository_feed = "repo"
category_feed = "cat"
package_feed = "cat/pkg"
versioned_feed = "cat/pkg-ver"
ebuild_feed = "cat/pkg-ver+text"

# The plugger needs to be able to compare those and know the highest one.
version_scope, package_scope, category_scope, repository_scope = range(4)
max_scope = repository_scope


class Addon(object):

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
    known_results = []

    def __init__(self, options, *args):
        """Initialize.

        An instance of every addon in required_addons is passed as extra arg.

        :param options: the optparse values.
        """
        self.options = options

    @staticmethod
    def mangle_option_parser(parser):
        """Add extra options and/or groups to the option parser.

        This hook is always triggered, even if the checker is not
        activated (because it runs before the commandline is parsed).

        :param parser: an C{OptionParser} instance.
        """

    @staticmethod
    def check_values(values):
        """Postprocess the optparse values.

        Should raise C{optparse.OptionValueError} on failure.

        This is only called for addons that are enabled, but before
        they are instantiated.
        """


class set_documentation(type):
    def __new__(cls, name, bases, d):
        if "__doc__" in d:
            d.setdefault("documentation", d["__doc__"])
        return type.__new__(cls, name, bases, d)


class Template(Addon):

    """Base template for a check."""

    __metaclass__ = set_documentation

    scope = 0
    # The plugger sorts based on this. Should be left alone except for
    # weird pseudo-checks like the cache wiper that influence other checks.
    priority = 0

    def start(self):
        """Do startup here."""

    def feed(self, item, reporter):
        raise NotImplementedError

    def finish(self, reporter):
        """Do cleanup and omit final results here."""


class Transform(object):

    """Base class for a feed type transformer.

    :cvar source: start type
    :cvar dest: destination type
    :cvar scope: minimun scope
    :cvar cost: cost
    """

    def __init__(self, child):
        self.child = child

    def start(self):
        """Startup."""
        self.child.start()

    def feed(self, item, reporter):
        raise NotImplementedError

    def finish(self, reporter):
        """Clean up."""
        self.child.finish(reporter)

    def __repr__(self):
        return '%s(%r)' % (self.__class__.__name__, self.child)

    def finish(self, reporter):
        pass


def _collect_checks(obj):
    if isinstance(obj, Transform):
        i = collect_checks(obj.child)
    elif isinstance(obj, CheckRunner):
        i = itertools.chain(*map(collect_checks, obj.checks))
    elif isinstance(obj, Addon):
        i = [obj]
    else:
        i = itertools.chain(*map(collect_checks, obj))
    for x in i:
        yield x


def collect_checks(obj):
    return set(_collect_checks(obj))


def collect_checks_classes(obj):
    return set(x.__class__ for x in collect_checks(obj))


class Result(object):

    __metaclass__ = set_documentation

    __slots__ = ()

    def __str__(self):
        try:
            return self.short_desc
        except NotImplementedError:
            return "result from %s" % self.__class__.__name__

    @property
    def short_desc(self):
        raise NotImplementedError

    @property
    def long_desc(self):
        return self.short_desc

    def _store_cp(self, pkg):
        self.category = pkg.category
        self.package = pkg.package

    def _store_cpv(self, pkg):
        self._store_cp(pkg)
        self.version = pkg.fullver

    def __getstate__(self):
        attrs = getattr(self, '__attrs__', getattr(self, '__slots__', None))
        if attrs:
            try:
                return dict((k, getattr(self, k)) for k in attrs)
            except AttributeError, a:
                # rethrow so we at least know the class
                raise AttributeError(self.__class__, str(a))
        return object.__getstate__(self)

    def __setstate__(self, data):
        attrs = set(getattr(self, '__attrs__', getattr(self, '__slots__', [])))
        if attrs.difference(data) or len(attrs) != len(data):
            raise TypeError("can't restore %s due to data %r not being complete" %
                            (self.__class__, data))
        for k, v in data.iteritems():
            setattr(self, k, v)


class Reporter(object):

    def add_report(self, result):
        raise NotImplementedError(self.add_report)

    def start(self):
        pass

    def start_check(self, source, target):
        pass

    def end_check(self):
        pass

    def finish(self):
        pass


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
            for i in xrange(len(chunks)):
                if chunks[i:i+len(toklist)] == toklist:
                    return True
            return False
        return func


class _CheckSet(object):

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
            if any(f('%s.%s' % (c.__module__, c.__name__))
                   for f in self.patterns))


class Blacklist(_CheckSet):

    """Only run checks not matching any of the provided patterns."""

    pkgcore_config_type = ConfigHint(
        {'patterns': 'list'}, typename='pkgcheck_checkset')

    def filter(self, checks):
        return list(
            c for c in checks
            if not any(f('%s.%s' % (c.__module__, c.__name__))
                       for f in self.patterns))


class Suite(object):

    pkgcore_config_type = ConfigHint({
        'target_repo': 'ref:repo', 'src_repo': 'ref:repo',
        'checkset': 'ref:pkgcheck_checkset'}, typename='pkgcheck_suite'
    )

    def __init__(self, target_repo, checkset=None, src_repo=None):
        self.target_repo = target_repo
        self.checkset = checkset
        self.src_repo = src_repo


class CheckRunner(object):

    def __init__(self, checks):
        self.checks = checks

    def start(self):
        for check in self.checks:
            # Intentionally not catching and logging exceptions:
            # if we fail this early we may as well abort.
            check.start()

    def feed(self, item, reporter):
        for check in self.checks:
            try:
                check.feed(item, reporter)
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception:
                logging.exception('check %r raised', check)

    def finish(self, reporter):
        for check in self.checks:
            try:
                check.finish(reporter)
            except Exception:
                logging.exception('finishing check %r failed', check)

    # The plugger tests use these.
    def __eq__(self, other):
        return self.__class__ is other.__class__ and \
            frozenset(self.checks) == frozenset(other.checks)

    def __ne__(self, other):
        return not self == other

    def __hash__(self):
        return hash(frozenset(self.checks))

    def __repr__(self):
        return '%s(%s)' % (self.__class__.__name__, ', '.join(
            sorted(str(check) for check in self.checks)))


def plug(sinks, transforms, sources, debug=None):
    """Plug together a pipeline.

    This tries to return a single pipeline if possible (even if it is
    more "expensive" than using separate pipelines). If more than one
    pipeline is needed it does not try to minimize the number.

    :param sinks: Sequence of check instances.
    :param transforms: Sequence of transform classes.
    :param sources: Sequence of source instances.
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

    assert sinks

    feed_to_transforms = {}
    for transform in transforms:
        feed_to_transforms.setdefault(transform.source, []).append(transform)

    # Map from typename to best scope
    best_scope = {}
    for source in sources:
        # (not particularly clever, if we get a ton of sources this
        # should be optimized to do less duplicate work).
        local_best_scope = {}
        reachable = set()
        todo = set([source.feed_type])
        while todo:
            feed_type = todo.pop()
            reachable.add(feed_type)
            for transform in feed_to_transforms.get(feed_type, ()):
                if transform.scope <= source.scope and \
                        transform.dest not in reachable:
                    todo.add(transform.dest)
        for feed_type in reachable:
            scope = best_scope.get(feed_type)
            if scope is None or scope < source.scope:
                best_scope[feed_type] = source.scope

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

    # Throw out all sources with a scope lower than the least required scope.
    # Does not check transform requirements, may not be very useful.
    lowest_required_scope = min(sink.scope for sink in good_sinks)
    highest_required_scope = max(sink.scope for sink in good_sinks)
    sources = list(s for s in sources if s.scope >= lowest_required_scope)
    if not sources:
        # No usable sources, abort.
        return bad_sinks + good_sinks, ()

    # All types we need to reach.
    sink_types = set(sink.feed_type for sink in good_sinks)

    # Map from scope, source typename to cheapest source.
    source_map = {}
    for new_source in sources:
        current_source = source_map.get((new_source.scope,
                                         new_source.feed_type))
        if current_source is None or current_source.cost > new_source.cost:
            source_map[new_source.scope, new_source.feed_type] = new_source

    # Tuples of (visited_types, source, transforms, price)
    pipes = set()
    unprocessed = set(
        (frozenset((source.feed_type,)), source, frozenset(), source.cost)
        for source in source_map.itervalues())
    if debug is not None:
        for pipe in unprocessed:
            debug('initial: %r', pipe)

    # If we find a single pipeline driving all sinks we want to use it.
    # List of tuples of source, transforms.
    pipes_to_run = None
    best_cost = None
    while unprocessed:
        next = unprocessed.pop()
        if next in pipes:
            continue
        pipes.add(next)
        visited, source, trans, cost = next
        if visited >= sink_types:
            # Already reaches all sink types. Check if it is usable as
            # single pipeline:
            if best_cost is None or cost < best_cost:
                pipes_to_run = [(source, trans)]
                best_cost = cost
            # No point in growing this further: it already reaches everything.
            continue
        if best_cost is not None and best_cost <= cost:
            # No point in growing this further.
            continue
        for transform in transforms:
            if source.scope >= transform.scope and \
                    transform.source in visited and \
                    transform.dest not in visited:
                unprocessed.add((
                    visited.union((transform.dest,)), source,
                    trans.union((transform,)), cost + transform.cost))
                if debug is not None:
                    debug(
                        'growing %r for %r with %r', trans, source, transform)

    if pipes_to_run is None:
        # No single pipe will drive everything, try combining pipes.
        # This is pretty stupid but effective. Map sources to
        # pipelines they drive, try combinations of sources (using a
        # source more than once in a combination makes no sense since
        # we also have the "combined" pipeline in pipes).
        source_to_pipes = {}
        for visited, source, trans, cost in pipes:
            source_to_pipes.setdefault(source, []).append(
                (visited, trans, cost))
        unprocessed = set(
            (visited, frozenset([source]), ((source, trans),), cost)
            for visited, source, trans, cost in pipes)
        done = set()
        while unprocessed:
            next = unprocessed.pop()
            if next in done:
                continue
            done.add(next)
            visited, sources, seq, cost = next
            if visited >= sink_types:
                # This combination reaches everything.
                if best_cost is None or cost < best_cost:
                    pipes_to_run = seq
                    best_cost = cost
                # No point in growing this further.
            if best_cost is not None and best_cost <= cost:
                # No point in growing this further.
                continue
            for source, source_pipes in source_to_pipes.iteritems():
                if source not in sources:
                    for new_visited, trans, new_cost in source_pipes:
                        unprocessed.add((
                            visited.union(new_visited),
                            sources.union([source]),
                            seq + ((source, trans),),
                            cost + new_cost))

    # Just an assert since unreachable sinks should have been thrown away.
    assert pipes_to_run, 'did not find a solution?'

    good_sinks.sort(key=attrgetter('priority'))

    def build_transform(scope, feed_type, transforms):
        children = list(
            # Note this relies on the cheapest pipe not having
            # any "loops" in its transforms.
            trans(build_transform(scope, trans.dest, transforms))
            for trans in transforms
            if trans.source == feed_type and trans.scope <= scope)
        # Hacky: we modify this in place.
        for i in reversed(xrange(len(good_sinks))):
            sink = good_sinks[i]
            if sink.feed_type == feed_type and sink.scope <= source.scope:
                children.append(sink)
                del good_sinks[i]
        return CheckRunner(children)

    result = list(
        (source, build_transform(source.scope, source.feed_type, transforms))
        for source, transforms in pipes_to_run)

    assert not good_sinks, 'sinks left: %r' % (good_sinks,)
    return bad_sinks, result
