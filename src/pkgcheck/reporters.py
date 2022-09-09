"""Basic result reporters."""

import csv
import json
from collections import defaultdict
from string import Formatter
from xml.sax.saxutils import escape as xml_escape

from snakeoil.decorators import coroutine

from . import base
from .results import BaseLinesResult, InvalidResult, Result


class Reporter:
    """Generic result reporter."""

    def __init__(self, out):
        """Initialize

        :type out: L{snakeoil.formatters.Formatter}
        """
        self.out = out

        # initialize result processing coroutines
        self.report = self._process_report().send

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

    @coroutine
    def _process_report(self):
        # scope to result prefix mapping
        scope_prefix_map = {
            base.version_scope: '{category}/{package}-{version}: ',
            base.package_scope: '{category}/{package}: ',
            base.category_scope: '{category}: ',
        }

        while True:
            result = (yield)
            prefix = scope_prefix_map.get(result.scope, '').format(**vars(result))
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

    @coroutine
    def _process_report(self):
        prev_key = None

        while True:
            result = (yield)
            if result.scope in (base.version_scope, base.package_scope):
                key = f'{result.category}/{result.package}'
            elif result.scope == base.category_scope:
                key = result.category
            else:
                key = result.scope.desc

            if key != prev_key:
                if prev_key is not None:
                    self.out.write()
                self.out.write(self.out.bold, self.out.fg('blue'), key, self.out.reset)
                prev_key = key
            self.out.first_prefix.append('  ')
            self.out.later_prefix.append('    ')
            s = ''
            if result.scope == base.version_scope:
                s = f"version {result.version}: "
            self.out.write(
                self.out.fg(result.color),
                result.name, self.out.reset,
                ': ', s, result.desc)
            self.out.first_prefix.pop()
            self.out.later_prefix.pop()
            self.out.stream.flush()


class JsonReporter(Reporter):
    """Feed of newline-delimited JSON records.

    Note that the format is newline-delimited JSON with each line being related
    to a separate report. To merge the objects together a tool such as jq can
    be leveraged similar to the following:

    .. code::

        jq -c -s 'reduce.[]as$x({};.*$x)' orig.json > new.json
    """

    priority = -1000

    @coroutine
    def _process_report(self):
        # arbitrarily nested defaultdicts
        json_dict = lambda: defaultdict(json_dict)
        # scope to data conversion mapping
        scope_map = {
            base.version_scope: lambda data, r: data[r.category][r.package][r.version],
            base.package_scope: lambda data, r: data[r.category][r.package],
            base.category_scope: lambda data, r: data[r.category],
        }

        while True:
            result = (yield)
            data = json_dict()
            d = scope_map.get(result.scope, lambda x, y: x)(data, result)
            d['_' + result.level][result.name] = result.desc
            self.out.write(json.dumps(data))
            # flush output so partial objects aren't written
            self.out.stream.flush()


class XmlReporter(Reporter):
    """Feed of newline-delimited XML reports."""

    priority = -1000

    def _start(self):
        self.out.write('<checks>')

    def _finish(self):
        self.out.write('</checks>')

    @coroutine
    def _process_report(self):
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

        while True:
            result = (yield)
            d = {k: getattr(result, k, '') for k in ('category', 'package', 'version')}
            d['class'] = xml_escape(result.name)
            d['msg'] = xml_escape(result.desc)
            self.out.write(scope_map.get(result.scope, result_template) % d)


class CsvReporter(Reporter):
    """Comma-separated value reporter, convenient for shell processing.

    Example::

        ,,,"global USE flag 'big-endian' is a potential local, used by 1 package: dev-java/icedtea-bin"
        sys-apps,portage,2.1-r2,sys-apps/portage-2.1-r2.ebuild has whitespace in indentation on line 169
        sys-apps,portage,2.1-r2,"rdepend  ppc-macos: unsolvable default-darwin/macos/10.4, solutions: [ >=app-misc/pax-utils-0.1.13 ]"
        sys-apps,portage,2.1-r2,"no change in 75 days, keywords [ ~x86-fbsd ]"
    """

    priority = -1001

    @coroutine
    def _process_report(self):
        writer = csv.writer(
            self.out,
            doublequote=False,
            escapechar='\\',
            lineterminator='')

        while True:
            result = (yield)
            writer.writerow((
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

    @coroutine
    def _process_report(self):
        formatter = _ResultFormatter()
        # provide expansions for result desc, level, and output name properties
        properties = ('desc', 'level', 'name')

        while True:
            result = (yield)
            attrs = vars(result)
            attrs.update((k, getattr(result, k)) for k in properties)
            s = formatter.format(self.format_str, **attrs)
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


class FlycheckReporter(Reporter):
    """Simple line reporter done for easier integration with flycheck [#]_ .

    .. [#] https://github.com/flycheck/flycheck
    """

    priority = -1001

    @coroutine
    def _process_report(self):
        while True:
            result = (yield)
            file = f'{getattr(result, "package", "")}-{getattr(result, "version", "")}.ebuild'
            message = f'{getattr(result, "name")}: {getattr(result, "desc")}'
            if isinstance(result, BaseLinesResult):
                message = message.replace(result.lines_str, '').strip()
                for lineno in result.lines:
                    self.out.write(f'{file}:{lineno}:{getattr(result, "level")}:{message}')
            else:
                lineno = getattr(result, "lineno", 0)
                self.out.write(f'{file}:{lineno}:{getattr(result, "level")}:{message}')
