"""Basic result reporters."""

import csv
import json
import pickle
from collections import defaultdict
from xml.sax.saxutils import escape as xml_escape

from snakeoil import pickling
from snakeoil.decorators import coroutine

from . import base, const


class StrReporter(base.Reporter):
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
            if result.threshold == base.versioned_feed:
                self.out.write(
                    f"{result.category}/{result.package}-{result.version}: {result.desc}")
            elif result.threshold == base.package_feed:
                self.out.write(f"{result.category}/{result.package}: {result.desc}")
            elif result.threshold == base.category_feed:
                self.out.write(f"{result.category}: {result.desc}")
            else:
                self.out.write(result.desc)
            self.out.stream.flush()


class FancyReporter(base.Reporter):
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
            if result.threshold in (base.versioned_feed, base.package_feed):
                key = f'{result.category}/{result.package}'
            elif result.threshold == base.category_feed:
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
            if result.threshold == base.versioned_feed:
                s = f"version {result.version}: "
            self.out.write(
                self.out.fg(result.color),
                result.__class__.__name__, self.out.reset,
                ': ', s, result.desc)
            self.out.first_prefix.pop()
            self.out.later_prefix.pop()
            self.out.stream.flush()


class NullReporter(base.Reporter):
    """Reporter used for timing tests; no output."""

    priority = -10000000

    @coroutine
    def _process_report(self):
        while True:
            _result = (yield)


class JsonReporter(base.Reporter):
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

            if result.threshold == base.repository_feed:
                d = data
            elif result.threshold == base.category_feed:
                d = data[result.category]
            elif result.threshold == base.package_feed:
                d = data[result.category][result.package]
            else:
                # versioned or ebuild feed
                d = data[result.category][result.package][result.version]

            name = result.__class__.__name__
            d['_' + result.level][name] = [result.desc]

            self.out.write(json.dumps(data))
            # flush output so partial objects aren't written
            self.out.stream.flush()


class XmlReporter(base.Reporter):
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

    threshold_map = {
        base.repository_feed: repo_template,
        base.category_feed: cat_template,
        base.package_feed: pkg_template,
        base.versioned_feed: ver_template,
        base.ebuild_feed: ver_template,
    }

    def start(self):
        self.out.write('<checks>')

    @coroutine
    def _process_report(self):
        while True:
            result = (yield)
            d = {k: getattr(result, k, '') for k in ('category', 'package', 'version')}
            d['class'] = xml_escape(result.__class__.__name__)
            d['msg'] = xml_escape(result.desc)
            self.out.write(self.threshold_map[result.threshold] % d)

    def finish(self):
        self.out.write('</checks>')


class CsvReporter(base.Reporter):
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


class FormatReporter(base.Reporter):
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


class JsonStream(base.Reporter):
    """Generate a stream of result objects serialized in JSON."""

    priority = -1001

    @staticmethod
    def to_json(result):
        """Serialize a result object to JSON."""
        d = {'__class__': result.__class__.__name__}
        d.update(result._attrs)
        return d

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
        category = d.pop('category', None)
        package = d.pop('package', None)
        version = d.pop('version', None)
        if any((category, package, version)):
            pkg = base.RawCPV(category, package, version)
            d['pkg'] = pkg

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


class PickleStream(base.Reporter):
    """Generate a stream of pickled objects using the original pickling protocol.

    For each specific target for checks, a header is pickled detailing the
    checks used, possible results, and search criteria.

    This reporter uses the original "human-readable" protocol that is backwards
    compatible with earlier versions of Python.
    """
    priority = -1001
    protocol = 0

    def start(self):
        self.out.wrap = False
        self.out.autoline = False

    @staticmethod
    def from_file(f):
        """Deserialize results from a given file handle."""
        try:
            for result in pickling.iter_stream(f):
                if isinstance(result, base.Result):
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
