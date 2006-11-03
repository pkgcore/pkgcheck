# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: GPL2

repository_feed = "repo"
category_feed = "cat"
package_feed = "cat/pkg"
versioned_feed = "cat/pkg-ver"

known_feeds = (repository_feed, category_feed, package_feed,
    versioned_feed)

__all__ = ("package_feed, versioned_feed", "category_feed", "Feeder")

import sys
import itertools, operator

from pkgcore.restrictions.util import collect_package_restrictions
from pkgcore_checks import util
from pkgcore.restrictions import packages
from pkgcore.util.demandload import demandload
demandload(globals(), "logging "
    "pkgcore.util:currying "
    "pkgcore.config.profiles ")


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


class Reporter(object):

    def __init__(self):
        self.reports = []
    
    def add_report(self, result):
        self.reports.append(result)

    def start(self):
        pass

    def finish(self):
        pass


class StrReporter(Reporter):

    def __init__(self, out):
        """Initialize.

        @type out: L{pkgcore.util.formatters.Formatter}.
        """
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


class XmlReporter(Reporter):

    def __init__(self, out):
        """Initialize.

        @type out: L{pkgcore.util.formatters.Formatter}.
        """
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


def plug(sinks, transforms, sources, reporter, debug=False):
    """Plug together a pipeline.

    sinks are check instances, transforms are transform instances,
    sources are source instances. For now at least.
    """
    required_types = frozenset(sink.feed_type for sink in sinks)
    assert required_types, 'no sources?'

    # The general idea is we will usually not have a large number of
    # sources/transforms, so we can simply bruteforce all possible
    # combinations (that are not loopy). This code is ridiculously
    # expensive from a complexity pov but since the loop lengths
    # involved are small I do not care.

    # This is a mapping of pipeline to (dest type, cost, types in it).
    pipelines = dict(
        ((source,),
         (source.feed_type, source.cost, frozenset((source.feed_type,))))
        for source in sources)
    # Add all possible transform combos.
    while True:
        progress = False
        for transform in transforms:
            for trans_source, trans_dest, trans_cost in transform.transforms:
                for pipe, (tail_type, cost, types) in pipelines.items():
                    if tail_type == trans_source and trans_dest not in types:
                        pipe = pipe + (transform,)
                        if pipe not in pipelines:
                            progress = True
                            pipelines[pipe] = (
                                trans_dest, cost + trans_cost, frozenset(
                                    tuple(types) + (trans_dest,)))
        if not progress:
            break

    # Now we look up the cheapest possible chain (or chains) that can
    # drive our sinks.

    # XXX this is naive, perhaps too naive.

    # We look up two things: the cheapest single pipeline that drives
    # all our sinks and the set of cheapest pipelines that each drive
    # at least one sink.

    # First try to find a single all-driving pipeline:
    best_single = None
    single_cost = sys.maxint
    for pipeline, (tail_type, cost, types) in pipelines.iteritems():
        if types >= required_types and cost < single_cost:
            best_single = pipeline
            single_cost = cost

    # Now find the set of (cheapest_pipeline, cost) tuples:
    multi_pipes = set()
    for required_type in required_types:
        best_cost = sys.maxint
        best_pipeline = None
        for pipeline, (tail_type, cost, types) in pipelines.iteritems():
            if tail_type == required_type and cost < best_cost:
                best_cost = cost
                best_pipeline = pipeline
        if best_pipeline is None:
            raise ValueError('No solution')
        multi_pipes.add((best_pipeline, best_cost))

    pipes, multi_cost = zip(*multi_pipes)
    multi_cost = sum(multi_cost)

    if debug:
        logging.warn('cost %s for %r' % (single_cost, best_single))
        logging.warn('cost %s for %r' % (multi_cost, pipes))

    if single_cost <= multi_cost:
        pipes = [best_single]

    # Plug the whole lot together.
    sink_map = {}
    for sink in sinks:
        sink_map.setdefault(sink.feed_type, []).append(sink)
    for pipe in pipes:
        pipe = list(reversed(pipe))
        source = pipe.pop()
        current_type = source.feed_type
        tail = source.feed()
        while True:
            sinks = sink_map.pop(current_type, ())
            for sink in sinks:
                tail = sink.feed(tail, reporter)
                assert tail is not None, '%r is not generating' % (sink,)
            if not pipe:
                break
            transform = pipe.pop()
            for source_type, target_type, cost in transform.transforms:
                if source_type == current_type:
                    current_type = target_type
                    break
            else:
                assert False, 'unreachable'
            tail = transform.transform(tail)
        yield tail
