# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# Copyright: 2006 Marien Zwart <marienz@gentoo.org>
# License: GPL2


"""Basic reporters and reporter factories."""

from pkgcore_checks import base
from pkgcore.config import configurable
from pkgcore.util import formatters, demandload

demandload.demandload(
    globals(),
    'pkgcore_checks:errors '
    'pkgcore.util:currying '
    )


class StrReporter(base.Reporter):

    """
    Simple string reporter, pcheck-0.1 behaviour. example:
    sys-apps/portage-2.1-r2: sys-apps/portage-2.1-r2.ebuild has whitespace in indentation on line 169
    sys-apps/portage-2.1-r2: rdepends  ppc-macos: unsolvable default-darwin/macos/10.4, solutions: [ >=app-misc/pax-utils-0.1.13 ]
    sys-apps/portage-2.1-r2: no change in 75 days, keywords [ ~x86-fbsd ]
    """

    # simple reporter; fallback default
    priority = 0

    def __init__(self, out):
        """Initialize.
        @type out: L{pkgcore.util.formatters.Formatter}.
        """
        base.Reporter.__init__(self)
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


class FancyReporter(base.Reporter):

    """
    groupped colored output, example:
    
    sys-apps/portage
      WrongIndentFound: sys-apps/portage-2.1-r2.ebuild has whitespace in indentation on line 169
      NonsolvableDeps: sys-apps/portage-2.1-r2: rdepends  ppc-macos: unsolvable default-darwin/macos/10.4, solutions: [ >=app-misc/pax-utils-0.1.13 ]
      StaleUnstableKeyword: sys-apps/portage-2.1-r2: no change in 75 days, keywords [ ~x86-fbsd ]
    """

    # default report, akin to repoman
    priority = 1

    def __init__(self, out):
        """Initialize.

        @type out: L{pkgcore.util.formatters.Formatter}.
        """
        base.Reporter.__init__(self)
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


class XmlReporter(base.Reporter):

    """
    dump an xml feed of reports
    """

    # xml report, shouldn't be used but in worst case.
    priority = -1000

    def __init__(self, out):
        """Initialize.

        @type out: L{pkgcore.util.formatters.Formatter}.
        """
        base.Reporter.__init__(self)
        self.out = out

    def start(self):
        self.out.write('<checks>')

    def add_report(self, result):
        self.out.write(result.to_xml())

    def finish(self):
        self.out.write('</checks>')


class PickleStream(base.Reporter):
    """
    Pickle each Result, and flush it
    
    """
    priority = -1001
    
    def __init__(self, out):
        """Initialize.

        @type out: L{pkgcore.util.formatters.Formatter}.
        """
        base.Reporter.__init__(self)
        self.out = out
        try:
            from cPickle import dump
        except ImportError:
            from Pickle import dump
        self.out.autoline = False
        self.out.wrap = False
        self.dump = dump

    def add_report(self, result):
        try:
            self.dump(result, self.out)
        except TypeError, t:
            raise TypeError(result, str(t))
    

class MultiplexReporter(base.Reporter):

    def __init__(self, *reporters):
        if len(reporters) < 2:
            raise ValueError("need at least two reporters")
        base.Reporter.__init__(self)
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
                raise errors.ReporterInitError(
                    'Cannot write to %r (%s)' % (dest, e))
            return klass(formatters.PlainTextFormatter(f))
        return reporter_factory
    return configurable_reporter_factory

xml_reporter = make_configurable_reporter_factory(XmlReporter)
xml_reporter.__name__ = 'xml_reporter'
plain_reporter = make_configurable_reporter_factory(StrReporter)
plain_reporter.__name__ = 'plain_reporter'
fancy_reporter = make_configurable_reporter_factory(FancyReporter)
fancy_reporter.__name__ = 'fancy_reporter'

@configurable({'reporters': 'refs:pcheck_reporter_factory'},
              typename='pcheck_reporter_factory')
def multiplex_reporter(reporters):
    def make_multiplex_reporter(out):
        return MultiplexReporter(*list(factory(out) for factory in reporters))
    return make_multiplex_reporter
