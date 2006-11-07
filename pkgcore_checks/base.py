# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: GPL2


"""Core classes and interfaces."""


import sys

from pkgcore.config import configurable
from pkgcore.util import formatters
from pkgcore.util.demandload import demandload
demandload(globals(), "logging ")


repository_feed = "repo"
category_feed = "cat"
package_feed = "cat/pkg"
versioned_feed = "cat/pkg-ver"

known_feeds = (repository_feed, category_feed, package_feed,
    versioned_feed)


class Addon(object):

    """Base class for extra functionality for pcheck other than a check.

    The checkers can depend on one or more of these. They will get
    called at various points where they can extend pcheck (if any
    active checks depend on the addon).

    These methods are not part of the checker interface because that
    would mean addon functionality shared by checkers would run twice.
    They are not plugins because they do not do anything useful if no
    checker depending on them is active.

    This interface is not finished. Expect it to grow more methods
    (but if not overridden they will be no-ops).

    @cvar required_addons: sequence of addons this one depends on.
    """

    required_addons = ()

    def __init__(self, options, *args):
        """Initialize.

        An instance of every addon in required_addons is passed as extra arg.

        @param options: the optparse values.
        """
        self.options = options

    @staticmethod
    def mangle_option_parser(parser):
        """Add extra options and/or groups to the option parser.

        This hook is always triggered, even if the checker is not
        activated (because it runs before the commandline is parsed).

        @param parser: an C{OptionParser} instance.
        """

    @staticmethod
    def check_values(values):
        """Postprocess the optparse values.

        Should raise C{optparse.OptionValueError} on failure.

        This is only called for addons that are enabled, but before
        they are instantiated.
        """


class Template(Addon):

    """Base template for a check."""

    def feed(self, chunk, reporter):
        raise NotImplementedError


class Result(object):

    def __str__(self):
        try:
            return self.to_str()
        except NotImplementedError:
            return "result from %s" % self.__class__.__name__
    
    def to_str(self):
        raise NotImplementedError
    
    def to_xml(self):
        raise NotImplementedError

    def _store_cp(self, pkg):
        self.category = pkg.category
        self.package = pkg.package
    
    def _store_cpv(self, pkg):
        self._store_cp(pkg)
        self.version = pkg.fullver


class ReporterInitError(Exception):
    """Raise this if a reporter factory fails."""


class Reporter(object):

    def add_report(self, result):
        raise NotImplementedError(self.add_report)

    def start(self):
        pass

    def finish(self):
        pass


class StrReporter(Reporter):

    def __init__(self, out):
        """Initialize.

        @type out: L{pkgcore.util.formatters.Formatter}.
        """
        Reporter.__init__(self)
        self.out = out
        self.first_report = True

    def add_report(self, result):
        if self.first_report:
            self.out.write()
            self.first_report = False
        self.out.write(result.to_str())

    def finish(self):
        if not self.first_report:
            self.out.write()


class FancyReporter(Reporter):

    def __init__(self, out):
        """Initialize.

        @type out: L{pkgcore.util.formatters.Formatter}.
        """
        Reporter.__init__(self)
        self.out = out
        self.key = None

    def add_report(self, result):
        cat = getattr(result, 'category', None)
        pkg = getattr(result, 'package', None)
        if cat is None or pkg is None:
            key = 'unknown'
        else:
            key = '%s/%s' % (cat, pkg)
        if key != self.key:
            self.out.write()
            self.out.write(self.out.bold, key)
            self.key = key
        self.out.first_prefix.append('  ')
        self.out.later_prefix.append('    ')
        self.out.write(
            self.out.fg('yellow'), result.__class__.__name__, self.out.reset,
            ': ', result.to_str())
        self.out.first_prefix.pop()
        self.out.later_prefix.pop()


class XmlReporter(Reporter):

    def __init__(self, out):
        """Initialize.

        @type out: L{pkgcore.util.formatters.Formatter}.
        """
        Reporter.__init__(self)
        self.out = out

    def start(self):
        self.out.write('<checks>')

    def add_report(self, result):
        self.out.write(result.to_xml())

    def finish(self):
        self.out.write('</checks>')


class MultiplexReporter(Reporter):

    def __init__(self, *reporters):
        if len(reporters) < 2:
            raise ValueError("need at least two reporters")
        Reporter.__init__(self)
        self.reporters = tuple(reporters)

    def start(self):
        for x in self.reporters:
            x.start()

    def add_report(self, result):
        for x in self.reporters:
            x.add_report(result)

    def finish(self):
        for x in self.reporters:
            x.finish()


def make_configurable_reporter_factory(klass):
    @configurable({'dest': 'str'}, typename='pcheck_reporter_factory')
    def configurable_reporter_factory(dest=None):
        if dest is None:
            return klass
        def reporter_factory(out):
            try:
                f = open(dest, 'w')
            except (IOError, OSError), e:
                raise ReporterInitError('Cannot write to %r (%s)' % (dest, e))
            return klass(formatters.PlainTextFormatter(f))
        return reporter_factory
    return configurable_reporter_factory

xml_reporter = make_configurable_reporter_factory(XmlReporter)
plain_reporter = make_configurable_reporter_factory(StrReporter)
fancy_reporter = make_configurable_reporter_factory(FancyReporter)

@configurable({'reporters': 'refs:pcheck_reporter_factory'},
              typename='pcheck_reporter_factory')
def multiplex_reporter(reporters):
    def make_multiplex_reporter(out):
        return MultiplexReporter(*list(factory(out) for factory in reporters))
    return make_multiplex_reporter


class _HalfPipe(object):

    """Internal helper."""

    def __init__(self, transforms, cost, end_type, passed_types=None):
        self.transforms = transforms
        self.cost = cost
        self.end_type = end_type
        if passed_types is None:
            passed_types = frozenset((end_type,))
        self.passed_types = passed_types

    def extend(self, halfpipe):
        return self.__class__(self.transforms + halfpipe.transforms,
                              self.cost + halfpipe.cost, halfpipe.end_type,
                              self.passed_types | halfpipe.passed_types)

    def __repr__(self):
        return '%s(%r, %r, %r, %r)' % (
            self.__class__.__name__, self.transforms, self.cost, self.end_type,
            self.passed_types)


class _Pipe(object):

    """Internal helper."""

    def __init__(self, source, transforms, cost, end_type, passed_types):
        self.source = source
        self.transforms = transforms
        self.cost = cost
        self.end_type = end_type
        self.passed_types = passed_types

    @classmethod
    def from_source(cls, source):
        return cls(
            source, (), source.cost, source.feed_type,
            frozenset((source.feed_type,)))

    @classmethod
    def from_halfpipe(cls, source, halfpipe):
        return cls(
            source, halfpipe.transforms, source.cost + halfpipe.cost,
            halfpipe.end_type, halfpipe.passed_types.union([source.feed_type]))

    def extend(self, halfpipe):
        return self.__class__(self.source,
                              self.transforms + halfpipe.transforms,
                              self.cost + halfpipe.cost, halfpipe.end_type,
                              self.passed_types | halfpipe.passed_types)

    def plug(self, sink_map, reporter):
        tail = self.source.feed()
        current_type = self.source.feed_type
        for sink in sink_map.pop(current_type, ()):
            tail = sink.feed(tail, reporter)
            assert tail is not None, '%r is not generating' % (sink,)
        for transform in self.transforms:
            for source_type, target_type, cost in transform.transforms:
                if source_type == current_type:
                    current_type = target_type
                    break
            else:
                assert False, 'unreachable'
            tail = transform.transform(tail)
            for sink in sink_map.pop(current_type, ()):
                tail = sink.feed(tail, reporter)
                assert tail is not None, '%r is not generating' % (sink,)
        return tail

    def __eq__(self, other):
        return (self.__class__ is other.__class__ and
                self.source == other.source and
                self.transforms == other.transforms and
                self.end_type == other.end_type)

    def __ne__(self, other):
        return not self == other

    def __hash__(self):
        return hash((self.source, self.transforms, self.end_type))

    def __repr__(self):
        return '%s(%r, %r, %r, %r, %s)' % (
            self.__class__.__name__, self.source, self.transforms, self.cost,
            self.end_type, '|'.join(repr(r) for r in self.passed_types))

def plug(sinks, transforms, sources, reporter, debug=False):
    """Plug together a pipeline.

    sinks are check instances, transforms are transform instances,
    sources are source instances. For now at least.
    """
    # The general idea is we will usually not have a large number of
    # types, so we can use a reasonably straightforward bruteforce
    # approach. We may have quite a bunch of sources, transforms or
    # sinks, but we only care about the cheapest of those for a type.

    # The plan:
    # - Build a matrix with the cheapest sequence of
    #   transforms for every source and target type.
    # - Use this matrix to build all runnable pipes: pipes that start at one
    #   of our sources and include at least one of our sinks.
    # - Report any sinks we cannot drive and throw those away.
    # - If we have one, return the cheapest single pipe driving all
    #   (remaining) sinks.
    # - Find the cheapest combination of pipes that drives all sinks
    #   and return that.

    # We prefer a single pipeline because this increases the
    # readability of our output.

    # Map from sink typename to sequence of sinks.
    sink_map = {}
    for sink in sinks:
        sink_map.setdefault(sink.feed_type, []).append(sink)

    # Map from source typename to cheapest source.
    source_map = {}
    for new_source in sources:
        current_source = source_map.get(new_source.feed_type)
        if current_source is None or current_source.cost > new_source.cost:
            source_map[new_source.feed_type] = new_source

    # Set of all types.
    types = set(source_map).union(sink_map)
    for transform in transforms:
        for source, dest, cost in transform.transforms:
            types.add(source)
            types.add(dest)

    # type_matrix[source, dest] -> HalfPipe
    type_matrix = {}

    # Initialize with basic transforms.
    for transform in transforms:
        for source, dest, cost in transform.transforms:
            # Pick the cheapest option if more than one basic
            # transform handles this.
            current_pipe = type_matrix.get((source, dest))
            if current_pipe is None or current_pipe.cost > cost:
                type_matrix[source, dest] = _HalfPipe((transform,), cost, dest)

    # Keep trying to build cheaper transforms.
    while True:
        progress = False
        # items, not iteritems, we manipulate in-place.
        for source in types:
            for dest in types:
                current_pipe = type_matrix.get((source, dest))
                for halfway in types:
                    first_half_pipe = type_matrix.get((source, halfway))
                    if first_half_pipe is None:
                        continue
                    second_half_pipe = type_matrix.get((halfway, dest))
                    if second_half_pipe is None:
                        continue
                    new_cost = first_half_pipe.cost + second_half_pipe.cost
                    if current_pipe is None or new_cost < current_pipe.cost:
                        progress = True
                        current_pipe = first_half_pipe.extend(second_half_pipe)
                        type_matrix[source, dest] = current_pipe
        if not progress:
            break

    if debug:
        for (source, dest), transform in type_matrix.iteritems():
            logging.warn('%s -> %s : %s', source, dest, transform)

    # _Pipe objects
    pipes = set()
    # Initialize for direct source-sink links and source-trans-sink:
    for source_type, source in source_map.iteritems():
        for sink_type in sink_map:
            if source_type == sink_type:
                # Initialize for direct source-sink link:
                pipes.add(_Pipe.from_source(source))
            else:
                halfpipe = type_matrix.get((source_type, sink_type))
                if halfpipe is not None:
                    # Add a source-transform-sink pipe:
                    pipes.add(_Pipe.from_halfpipe(source, halfpipe))

    if debug:
        for pipe in pipes:
            logging.warn('initial: %r', pipe)

    # Try to grow longer pipes:
    while True:
        # Python does not like it if you change the set during iteration.
        new_pipes = []
        for pipe in pipes:
            for sink_type in sink_map:
                if sink_type in pipe.passed_types:
                    continue
                trans_pipe = type_matrix.get((pipe.end_type, sink_type))
                if trans_pipe is None:
                    continue
                new_pipe = pipe.extend(trans_pipe)
                if new_pipe not in pipes:
                    new_pipes.append(new_pipe)
        if not new_pipes:
            break
        pipes.update(new_pipes)

        if debug:
            for pipe in new_pipes:
                logging.warn('adding: %r', pipe)

    # Check if we have unreachable types:
    all_passed = set()
    for pipe in pipes:
        all_passed |= pipe.passed_types
    unreachables = set(sink_map) - all_passed
    # TODO report these
    for unreachable in unreachables:
        logging.warning('%r unreachable', unreachable)
        del sink_map[unreachable]

    # Try to find a single pipeline that drives everything.
    everything = frozenset(sink_map)
    best_pipe = None
    # And simultaneously build up the map from sink type to pipes.
    sink_pipes = {}
    for pipe in pipes:
        if pipe.passed_types == everything:
            if best_pipe is None or best_pipe.cost > pipe.cost:
                best_pipe = pipe
        for passed_type in pipe.passed_types:
            sink_pipes.setdefault(passed_type, []).append(pipe)
    if best_pipe is not None:
        # Done!
        return [best_pipe.plug(sink_map, reporter)]

    def generate_pipes(pipes, todo):
        if todo:
            for sink_type in todo:
                for pipe in sink_pipes[sink_type]:
                    for res in generate_pipes(pipes + [pipe],
                                              todo - pipe.passed_types):
                        yield res
        else:
            yield pipes

    best_pipes = None
    best_cost = 0
    for pipelist in generate_pipes([], everything):
        cost = sum(pipe.cost for pipe in pipelist)
        if best_pipes is None or best_cost > cost:
            best_pipes = pipelist
            best_cost = cost

    # Just an assert, since all types in everything are reachable.
    assert best_pipes is not None

    return list(pipe.plug(sink_map, reporter) for pipe in best_pipes)
