"""Basic result reporters."""

import csv
import json
import pickle
from collections import defaultdict
from string import Formatter
from xml.sax.saxutils import escape as xml_escape

from snakeoil import pickling
from snakeoil.decorators import coroutine

from . import base
from .results import InvalidResult, Result


class Reporter:
    """Generic result reporter."""

    def __init__(self, out):
        """Initialize

        :type out: L{snakeoil.formatters.Formatter}
        """
        self.out = out

        # initialize result processing coroutines
        self.report = self._process_report().send

    def __call__(self, pipe):
        for result in pipe:
            self.report(result)
        return pipe.exit_status

    def __enter__(self):
        self._start()
        return self

    def __exit__(self, *excinfo):
        self._finish()
        # flush output buffer
        self.out.stream.flush()

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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # scope to result prefix mapping
        self._scope_prefix_map = {
            base.version_scope: '{category}/{package}-{version}: ',
            base.package_scope: '{category}/{package}: ',
            base.category_scope: '{category}: ',
        }

    @coroutine
    def _process_report(self):
        while True:
            result = (yield)
            prefix = self._scope_prefix_map.get(result.scope, '').format(**vars(result))
            self.out.write(f'{prefix}{result.desc}')
            self.out.stream.flush()


class FancyReporter(Reporter):
    """Colored output grouped by result scope.

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
            elif result.scope is base.category_scope:
                key = result.category
            else:
                key = str(result.scope)

            if key != self.key:
                if self.key is not None:
                    self.out.write()
                self.out.write(self.out.bold, key)
                self.key = key
            self.out.first_prefix.append('  ')
            self.out.later_prefix.append('    ')
            s = ''
            if result.scope is base.version_scope:
                s = f"version {result.version}: "
            self.out.write(
                self.out.fg(result.color),
                result.name, self.out.reset,
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
            _ = (yield)


class JsonReporter(Reporter):
    """Feed of newline-delimited JSON records.

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
        # scope to data conversion mapping
        self._scope_map = {
            base.version_scope: lambda data, r: data[r.category][r.package][r.version],
            base.package_scope: lambda data, r: data[r.category][r.package],
            base.category_scope: lambda data, r: data[r.category],
        }

    @coroutine
    def _process_report(self):
        while True:
            result = (yield)
            data = self._json_dict()
            d = self._scope_map.get(result.scope, lambda x, y: x)(data, result)
            d['_' + result.level][result.name] = result.desc
            self.out.write(json.dumps(data))
            # flush output so partial objects aren't written
            self.out.stream.flush()


class XmlReporter(Reporter):
    """Feed of newline-delimited XML reports."""

    priority = -1000

    result_template = (
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
            d['class'] = xml_escape(result.name)
            d['msg'] = xml_escape(result.desc)
            self.out.write(self.scope_map.get(result.scope, self.result_template) % d)


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


class _ResultFormatter(Formatter):
    """Custom string formatter that collapses unmatched variables."""

    def get_value(self, key, args, kwds):
        """Retrieve a given field value, an empty string is returned for unmatched fields."""
        if isinstance(key, str):
            try:
                return kwds[key]
            except KeyError:
                return ''
        raise base.PkgcheckUserException(
            'FormatReporter: integer indexes are not supported')


class FormatReporter(Reporter):
    """Custom format string reporter."""

    priority = -1001

    def __init__(self, format_str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.format_str = format_str
        self._formatter = _ResultFormatter()
        # provide expansions for result desc, level, and output name properties
        self._properties = ('desc', 'level', 'name')

    @coroutine
    def _process_report(self):
        while True:
            result = (yield)
            attrs = vars(result)
            attrs.update((k, getattr(result, k)) for k in self._properties)
            s = self._formatter.format(self.format_str, **attrs)
            # output strings with at least one valid expansion or non-whitespace character
            if s.strip():
                self.out.write(s)
                self.out.stream.flush()


class DeserializationError(Exception):
    """Exception occurred while deserializing a data stream."""


class JsonStream(Reporter):
    """Generate a stream of result objects serialized in JSON."""

    priority = -1001

    @staticmethod
    def to_json(obj):
        """Serialize results and other objects to JSON."""
        if isinstance(obj, Result):
            d = {'__class__': obj.__class__.__name__}
            d.update(obj._attrs)
            return d
        return str(obj)

    @staticmethod
    def from_iter(iterable):
        """Deserialize results from a given iterable."""
        # avoid circular import issues
        from . import objects
        try:
            for data in map(json.loads, iterable):
                cls = objects.KEYWORDS[data.pop('__class__')]
                yield cls._create(**data)
        except (json.decoder.JSONDecodeError, UnicodeDecodeError, DeserializationError) as e:
            raise DeserializationError('failed loading') from e
        except (KeyError, InvalidResult):
            raise DeserializationError('unknown result')

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
                if isinstance(result, Result):
                    yield result
                else:
                    raise DeserializationError(f'invalid data type: {result!r}')
        except (pickle.UnpicklingError, TypeError) as e:
            raise DeserializationError('failed unpickling result') from e

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
