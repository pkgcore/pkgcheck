#!/usr/bin/python

"""Replay a pickled results stream from pkgcheck, feeding the results into a reporter.

Useful if you need to delay acting on results until it can be done in
one minimal window (say updating a database), or want to generate
several different reports without using a config defined multiplex reporter.
"""

from __future__ import absolute_import

from pkgcore.util import commandline
from snakeoil.demandload import demandload

from pkgcheck import base

demandload(
    'os',
    'snakeoil:pickling,formatters',
    'snakeoil.modules:load_attribute',
    'pkgcheck:reporters',
)


class StreamHeader(object):

    def __init__(self, checks, criteria):
        self.checks = sorted((x for x in checks if x.known_results),
                             key=lambda x: x.__name__)
        self.known_results = set()
        for x in checks:
            self.known_results.update(x.known_results)

        self.known_results = tuple(sorted(self.known_results))
        self.criteria = str(criteria)


class PickleStream(base.Reporter):
    """Generate a stream of pickled objects.

    For each specific target for checks, a header is pickled
    detailing the checks used, possible results, and search
    criteria.
    """
    priority = -1001
    protocol = 0

    def __init__(self, out):
        """Initialize.

        :type out: L{snakeoil.formatters.Formatter}.
        """
        base.Reporter.__init__(self)
        self.out = out
        self.dump = pickling.dump

    def start(self):
        self.out.wrap = False
        self.out.autoline = False

    def start_check(self, checks, target):
        self.dump(StreamHeader(checks, target), self.out)

    def add_report(self, result):
        try:
            self.dump(result, self.out, self.protocol)
        except TypeError as t:
            raise TypeError(result, str(t))


class BinaryPickleStream(PickleStream):
    """Dump a binary pickle stream (highest protocol).

    For details of the stream, see PickleStream
    """
    priority = -1002
    protocol = -1


argparser = commandline.ArgumentParser(
    config=False, domain=False, color=False, description=__doc__)
argparser.add_argument(
    dest='pickle_file', help='pickled results file')
argparser.add_argument(
    dest='reporter', help='python namespace path reporter to replay it into')
argparser.add_argument(
    '--out', default=None, help='redirect reporters output to a file')


@argparser.bind_final_check
def check_args(parser, namespace):
    if not os.path.isfile(namespace.pickle_file):
        parser.error("pickle file doesn't exist: %r" % namespace.pickle_file)


def replay_stream(stream_handle, reporter, debug=None):
    headers = []
    last_count = 0
    for count, item in enumerate(pickling.iter_stream(stream_handle)):
        if isinstance(item, StreamHeader):
            if debug:
                if headers:
                    debug.write("finished processing %i results for %s" %
                                (count - last_count, headers[-1].criteria))
                last_count = count
                debug.write("encountered new stream header for %s" %
                            item.criteria)
            if headers:
                reporter.end_check()
            reporter.start_check(item.checks, item.criteria)
            headers.append(item)
            continue
        reporter.add_report(item)
    if headers:
        reporter.end_check()
        if debug:
            debug.write(
                "finished processing %i results for %s" %
                (count - last_count, headers[-1].criteria))


@argparser.bind_main_func
def main(options, out, err):
    if options.out:
        out = formatters.get_formatter(open(options.out, 'w'))
    debug = None
    if options.debug:
        debug = err
    replay_stream(
        open(options.stream_path), options.reporter(out), debug=debug)
    return 0
