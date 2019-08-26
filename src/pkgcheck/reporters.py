"""Basic result reporters."""

from collections import defaultdict
import json
import pickle
from xml.sax.saxutils import escape as xml_escape

from snakeoil import currying, formatters
from snakeoil.cli.exceptions import UserException
from snakeoil.decorators import coroutine

from . import base, const


class StrReporter(base.Reporter):
    """Simple string reporter, pkgcheck-0.1 behaviour.

    Example::

        sys-apps/portage-2.1-r2: sys-apps/portage-2.1-r2.ebuild has whitespace in indentation on line 169
        sys-apps/portage-2.1-r2: rdepend  ppc-macos: unsolvable default-darwin/macos/10.4, solutions: [ >=app-misc/pax-utils-0.1.13 ]
        sys-apps/portage-2.1-r2: no change in 75 days, keywords [ ~x86-fbsd ]
    """

    # simple reporter; fallback default
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

    # default report, akin to repoman
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
    """reporter used for timing tests; no output"""

    priority = -10000000

    @coroutine
    def _process_report(self):
        while True:
            result = (yield)


class JsonReporter(base.Reporter):
    """Dump a json feed of reports.

    Note that the format is newline-delimited JSON with each line being related
    to a separate report. To merge the objects together a tool such as jq can
    be leveraged similar to the following:

    .. code::

        jq -c -s 'reduce.[]as$x({};.*$x)' orig.json > new.json
    """

    # json report should only be used if requested
    priority = -1000

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
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

    # xml report, shouldn't be used but in worst case.
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def start(self):
        self.out.write('<checks>')

    @coroutine
    def _process_report(self):
        while True:
            result = (yield)
            d = dict((k, getattr(result, k, '')) for k in
                    ("category", "package", "version"))
            d["class"] = xml_escape(result.__class__.__name__)
            d["msg"] = xml_escape(result.desc)
            self.out.write(self.threshold_map[result.threshold] % d)

    def finish(self):
        self.out.write('</checks>')


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
        d = json.loads(data)
        try:
            cls = const.KEYWORDS[d.pop('__class__')]
        except KeyError:
            raise UserException('old or invalid JSON results file')

        # reconstruct a package object
        category = d.pop('category', None)
        package = d.pop('package', None)
        version = d.pop('version', None)
        if any((category, package, version)):
            pkg = base.RawCPV(category, package, version)
            d['pkg'] = pkg

        return cls(**d)

    @coroutine
    def _process_report(self):
        while True:
            result = (yield)
            data = json.dumps(result, default=self.to_json)
            self.out.write(data)


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
