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


def plug(sinks, transforms, sources, reporter, debug=None):
    """Plug together a pipeline.

    sinks are check instances, transforms are transform instances,
    sources are source instances. For now at least.

    @param sinks: Sequence of check instances.
    @param transforms: Sequence of transform instances.
    @param sources: Sequence of source instances.
    @param reporter: reporter instance.
    @param debug: A logging function or C{None}.
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

    # type_matrix[source, dest] -> (cost, transforms)
    type_matrix = {}

    # Initialize with basic transforms.
    for transform in transforms:
        for source, dest, cost in transform.transforms:
            # Pick the cheapest option if more than one basic
            # transform handles this.
            current_pipe = type_matrix.get((source, dest))
            if current_pipe is None or current_pipe[0] > cost:
                type_matrix[source, dest] = (cost, (transform,))

    # Keep trying to build cheaper transforms.
    while True:
        progress = False
        for source in types:
            for dest in types:
                if source == dest:
                    continue
                current_pipe = type_matrix.get((source, dest))
                for halfway in types:
                    first_half_pipe = type_matrix.get((source, halfway))
                    if first_half_pipe is None:
                        continue
                    second_half_pipe = type_matrix.get((halfway, dest))
                    if second_half_pipe is None:
                        continue
                    new_cost = first_half_pipe[0] + second_half_pipe[0]
                    if current_pipe is None or new_cost < current_pipe[0]:
                        progress = True
                        current_cost = new_cost
                        current_pipe = (
                            new_cost, first_half_pipe[1] + second_half_pipe[1])
                        type_matrix[source, dest] = current_pipe
                        # Do not break out of the loop: we may hit a
                        # combination that is even cheaper.
        if not progress:
            break

    if debug is not None:
        for (source, dest), (cost, pipe) in type_matrix.iteritems():
            debug('%s -> %s : %s (%s)', source, dest, pipe, cost)

    # Tuples of price followed by tuple of visited types.
    # Includes sources with no "direct" sinks for simplicity.
    pipes = []
    unprocessed = list((source.cost, (source_type,))
                       for source_type, source in source_map.iteritems())
    if debug is not None:
        for pipe in unprocessed:
            debug('initial: %r', pipe)
    # Try to grow longer pipes.
    while unprocessed:
        cost, pipe = unprocessed.pop(0)
        pipes.append((cost, pipe))
        for sink_type in sink_map:
            if sink_type in pipe:
                continue
            halfpipe = type_matrix.get((pipe[-1], sink_type))
            if halfpipe is not None:
                unprocessed.append((cost + halfpipe[0], pipe + (sink_type,)))
                if debug is not None:
                    debug('growing %r with %r', pipe, sink_type)

    # Check if we have unreachable types:
    all_passed = set()
    for cost, pipe in pipes:
        all_passed.update(pipe)
    unreachables = set(sink_map) - all_passed
    # TODO report these
    for unreachable in unreachables:
        logging.warning('%r unreachable', unreachable)
        del sink_map[unreachable]

    # Try to find a single pipeline that drives everything we can drive.
    all_sink_types = frozenset(sink_map)
    best_pipe = None
    best_cost = 0
    # And build up the map from sink type to (cost, pipe) tuples
    sink_pipes = {}
    for cost, pipe in pipes:
        # Why ">="? Because we include the source we start from in the pipe.
        if frozenset(pipe) >= all_sink_types:
            if best_pipe is None or best_cost > cost:
                best_pipe = pipe
                best_cost = cost
        for passed_type in pipe:
            sink_pipes.setdefault(passed_type, []).append((cost, pipe))

    if best_pipe is not None:
        to_run = [best_pipe]
    else:
        def generate_pipes(pipes, todo):
            if todo:
                for sink_type in todo:
                    for cost, pipe in sink_pipes[sink_type]:
                        for res in generate_pipes(pipes + [(cost, pipe)],
                                                  todo.difference(pipe)):
                            yield res
            else:
                yield pipes

        best_pipes = None
        best_cost = 0
        for pipelist in generate_pipes([], all_sink_types):
            cost = sum(cost for cost, pipe in pipelist)
            if best_pipes is None or best_cost > cost:
                best_pipes = pipelist
                best_cost = cost

        # Just an assert, since all types in all_sink_types are reachable.
        assert best_pipes is not None
        to_run = list(pipe for cost, pipe in best_pipes)

    #return list(pipe.plug(sink_map, reporter) for pipe in best_pipes)
    for pipe in to_run:
        current_type = pipe[0]
        source = source_map[current_type]
        tail = source.feed()
        # Everything except for the source, reversed.
        types_left = list(pipe[-1:0:-1])
        while True:
            # The default value here *should* only be triggered for the source.
            for sink in sink_map.pop(current_type, ()):
                tail = sink.feed(tail, reporter)
                assert tail is not None, '%r is not generating' % (sink,)
            if not types_left:
                break
            new_type = types_left.pop()
            for transform in type_matrix[current_type, new_type][1]:
                for source_type, target_type, cost in transform.transforms:
                    if source_type == current_type:
                        current_type = target_type
                        break
                else:
                    assert False, 'unreachable'
                tail = transform.transform(tail)
                current_type = target_type
        yield tail
