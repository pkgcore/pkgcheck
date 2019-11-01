"""Basic result reporters."""

import csv
import json
import pickle
import signal
from collections import defaultdict
from itertools import chain
from multiprocessing import Process, SimpleQueue
from xml.sax.saxutils import escape as xml_escape

from snakeoil import pickling
from snakeoil.decorators import coroutine

from . import base, const, results


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

    def __call__(self, pipe):
        results_q = SimpleQueue()
        orig_sigint_handler = signal.signal(signal.SIGINT, signal.SIG_DFL)
        p = Process(target=pipe.run, args=(results_q,))
        p.start()
        signal.signal(signal.SIGINT, orig_sigint_handler)
        if pipe.pkg_scan:
            # sort versioned package results, removing duplicate MetadataError results
            results = set(chain.from_iterable(iter(results_q.get, None)))
            for result in sorted(results):
                self.report(result)
        else:
            for results in iter(results_q.get, None):
                for result in sorted(results):
                    self.report(result)
        p.join()

    def __enter__(self):
        self._start()
        return self

    def __exit__(self, *excinfo):
        self._finish()
        # flush output buffer
        self.out.stream.flush()

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

    def _start(self):
        """Initialize reporter output."""

    def _finish(self):
        """Finalize reporter output."""


class StrReporter(Reporter):
    """Simple string reporter, pkgcheck-0.1 behaviour.

    Example::

        sys-apps/portage-2.1-r2: sys-apps/portage-2.1-r2.ebuild has whitespace in indentation on line 169
        sys-apps/portage-2.1-r2: rdepend  ppc-macos: unsolvable default-darwin/macos/10.4, solutions: [ >=app-misc/pax-utils-0.1.13 ]
        sys-apps/portage-2.1-r2: no change in 75 days, keywords [ ~x86-fbsd ]
    """

    priority = 0

    @coroutine
    def _process_report(self):
        while True:
            result = (yield)
            if result.scope == base.version_scope:
                self.out.write(
                    f"{result.category}/{result.package}-{result.version}: {result.desc}")
            elif result.scope == base.package_scope:
                self.out.write(f"{result.category}/{result.package}: {result.desc}")
            elif result.scope == base.category_scope:
                self.out.write(f"{result.category}: {result.desc}")
            else:
                self.out.write(result.desc)
            self.out.stream.flush()


class FancyReporter(Reporter):
    """grouped colored output

    Example::

        sys-apps/portage
          WrongIndentFound: sys-apps/portage-2.1-r2.ebuild has whitespace in indentation on line 169
          NonsolvableDeps: sys-apps/portage-2.1-r2: rdepend  ppc-macos: unsolvable default-darwin/macos/10.4, solutions: [ >=app-misc/pax-utils-0.1.13 ]
          StableRequest: sys-apps/portage-2.1-r2: no change in 75 days, keywords [ ~x86 ]
    """

    priority = 1

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.key = None

    @coroutine
    def _process_report(self):
        while True:
            result = (yield)
            if result.scope in (base.version_scope, base.package_scope):
                key = f'{result.category}/{result.package}'
            elif result.scope == base.category_scope:
                key = result.category
            else:
                key = 'repo'

            if key != self.key:
                if self.key is not None:
                    self.out.write()
                self.out.write(self.out.bold, key)
                self.key = key
            self.out.first_prefix.append('  ')
            self.out.later_prefix.append('    ')
            s = ''
            if result.scope == base.version_scope:
                s = f"version {result.version}: "
            self.out.write(
                self.out.fg(result.color),
                result.__class__.__name__, self.out.reset,
                ': ', s, result.desc)
            self.out.first_prefix.pop()
            self.out.later_prefix.pop()
            self.out.stream.flush()


class NullReporter(Reporter):
    """Reporter used for timing tests; no output."""

    priority = -10000000

    @coroutine
    def _process_report(self):
        while True:
            _result = (yield)


class JsonReporter(Reporter):
    """Dump a json feed of reports.

    Note that the format is newline-delimited JSON with each line being related
    to a separate report. To merge the objects together a tool such as jq can
    be leveraged similar to the following:

    .. code::

        jq -c -s 'reduce.[]as$x({};.*$x)' orig.json > new.json
    """

    priority = -1000

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # arbitrarily nested defaultdicts
        self._json_dict = lambda: defaultdict(self._json_dict)

    @coroutine
    def _process_report(self):
        while True:
            result = (yield)
            data = self._json_dict()

            if result.scope == base.repository_scope:
                d = data
            elif result.scope == base.category_scope:
                d = data[result.category]
            elif result.scope == base.package_scope:
                d = data[result.category][result.package]
            else:
                # versioned or ebuild feed
                d = data[result.category][result.package][result.version]

            name = result.__class__.__name__
            d['_' + result.level][name] = [result.desc]

            self.out.write(json.dumps(data))
            # flush output so partial objects aren't written
            self.out.stream.flush()


class XmlReporter(Reporter):
    """dump an xml feed of reports"""

    priority = -1000

    repo_template = (
        "<result><class>%(class)s</class>"
        "<msg>%(msg)s</msg></result>")
    cat_template = (
        "<result><category>%(category)s</category>"
        "<class>%(class)s</class><msg>%(msg)s</msg></result>")
    pkg_template = (
        "<result><category>%(category)s</category>"
        "<package>%(package)s</package><class>%(class)s</class>"
        "<msg>%(msg)s</msg></result>")
    ver_template = (
        "<result><category>%(category)s</category>"
        "<package>%(package)s</package><version>%(version)s</version>"
        "<class>%(class)s</class><msg>%(msg)s</msg></result>")

    scope_map = {
        base.repository_scope: repo_template,
        base.category_scope: cat_template,
        base.package_scope: pkg_template,
        base.version_scope: ver_template,
    }

    def _start(self):
        self.out.write('<checks>')

    def _finish(self):
        self.out.write('</checks>')

    @coroutine
    def _process_report(self):
        while True:
            result = (yield)
            d = {k: getattr(result, k, '') for k in ('category', 'package', 'version')}
            d['class'] = xml_escape(result.__class__.__name__)
            d['msg'] = xml_escape(result.desc)
            self.out.write(self.scope_map[result.scope] % d)


class CsvReporter(Reporter):
    """Comma-separated value reporter, convenient for shell processing.

    Example::

        ,,,"global USE flag 'big-endian' is a potential local, used by 1 package: dev-java/icedtea-bin"
        sys-apps,portage,2.1-r2,sys-apps/portage-2.1-r2.ebuild has whitespace in indentation on line 169
        sys-apps,portage,2.1-r2,"rdepend  ppc-macos: unsolvable default-darwin/macos/10.4, solutions: [ >=app-misc/pax-utils-0.1.13 ]"
        sys-apps,portage,2.1-r2,"no change in 75 days, keywords [ ~x86-fbsd ]"
    """

    priority = -1001

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._writer = csv.writer(
            self.out,
            doublequote=False,
            escapechar='\\',
            lineterminator='')

    @coroutine
    def _process_report(self):
        while True:
            result = (yield)
            self._writer.writerow((
                getattr(result, 'category', ''),
                getattr(result, 'package', ''),
                getattr(result, 'version', ''),
                result.desc))


class FormatReporter(Reporter):
    """Custom format string reporter."""

    priority = -1001

    def __init__(self, format_str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.format_str = format_str
        # provide expansions for result desc and level properties
        self._properties = ('desc', 'level')

    @coroutine
    def _process_report(self):
        while True:
            result = (yield)
            attrs = vars(result)
            attrs.update((k, getattr(result, k)) for k in self._properties)
            try:
                self.out.write(self.format_str.format(**attrs))
                self.out.stream.flush()
            except KeyError:
                # ignore results missing requested attributes
                pass


class DeserializationError(Exception):
    """Exception occurred while deserializing a data stream."""


class JsonStream(Reporter):
    """Generate a stream of result objects serialized in JSON."""

    priority = -1001

    @staticmethod
    def to_json(obj):
        """Serialize results and other objects to JSON."""
        if isinstance(obj, results.Result):
            d = {'__class__': obj.__class__.__name__}
            d.update(obj._attrs)
            return d
        return str(obj)

    @staticmethod
    def from_json(data):
        """Deserialize JSON object to its corresponding result object."""
        try:
            d = json.loads(data)
        except (json.decoder.JSONDecodeError, UnicodeDecodeError) as e:
            raise DeserializationError(f'failed loading: {data!r}') from e

        try:
            cls = const.KEYWORDS[d.pop('__class__')]
        except KeyError:
            raise DeserializationError(f'missing result class: {data!r}')

        # reconstruct a package object
        d = results.Result.attrs_to_pkg(d)

        try:
            return cls(**d)
        except TypeError as e:
            raise DeserializationError(f'failed loading: {data!r}') from e

    @classmethod
    def from_file(cls, f):
        """Deserialize results from a given file handle."""
        try:
            for i, line in enumerate(f, 1):
                yield cls.from_json(line)
        except DeserializationError as e:
            raise DeserializationError(f'invalid entry on line {i}') from e

    @coroutine
    def _process_report(self):
        while True:
            result = (yield)
            self.out.write(json.dumps(result, default=self.to_json))


class PickleStream(Reporter):
    """Generate a stream of pickled objects using the original pickling protocol.

    For each specific target for checks, a header is pickled detailing the
    checks used, possible results, and search criteria.

    This reporter uses the original "human-readable" protocol that is backwards
    compatible with earlier versions of Python.
    """
    priority = -1001
    protocol = 0

    def _start(self):
        self.out.wrap = False
        self.out.autoline = False

    @staticmethod
    def from_file(f):
        """Deserialize results from a given file handle."""
        try:
            for result in pickling.iter_stream(f):
                if isinstance(result, results.Result):
                    yield result
                else:
                    raise DeserializationError(f'invalid data type: {result!r}')
        except pickle.UnpicklingError as e:
            raise DeserializationError(f'failed unpickling result') from e

    @coroutine
    def _process_report(self):
        while True:
            result = (yield)
            try:
                pickle.dump(result, self.out.stream, self.protocol)
            except (AttributeError, TypeError) as e:
                raise TypeError(result, str(e))


class BinaryPickleStream(PickleStream):
    """Dump a binary pickle stream using the highest pickling protocol.

    Unlike `PickleStream`_ which uses the most compatible pickling protocol
    available, this uses the newest version so it won't be compatible with
    older versions of Python.

    For more details of the stream, see `PickleStream`_.
    """
    priority = -1002
    protocol = -1
