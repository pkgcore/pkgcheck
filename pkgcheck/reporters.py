# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# Copyright: 2006 Marien Zwart <marienz@gentoo.org>
# License: BSD/GPL2


"""Basic reporters and reporter factories."""

from pkgcore.config import configurable
from snakeoil import formatters

from pkgcheck import base

from snakeoil.demandload import demandload
demandload(
    'pkgcheck:errors',
    'snakeoil:currying',
    'snakeoil:pickling',
    'snakeoil:xml',
)


class StrReporter(base.Reporter):

    """
    Simple string reporter, pkgcheck-0.1 behaviour. example:
    sys-apps/portage-2.1-r2: sys-apps/portage-2.1-r2.ebuild has whitespace in indentation on line 169
    sys-apps/portage-2.1-r2: rdepends  ppc-macos: unsolvable default-darwin/macos/10.4, solutions: [ >=app-misc/pax-utils-0.1.13 ]
    sys-apps/portage-2.1-r2: no change in 75 days, keywords [ ~x86-fbsd ]
    """

    # simple reporter; fallback default
    priority = 0

    def __init__(self, out):
        """Initialize.
        :type out: L{snakeoil.formatters.Formatter}.
        """
        base.Reporter.__init__(self)
        self.out = out
        self.first_report = True

    def add_report(self, result):
        if self.first_report:
            self.out.write()
            self.first_report = False
        if result.threshold == base.versioned_feed:
            self.out.write("%s/%s-%s: %s" % (result.category, result.package,
                result.version, result.short_desc))
        elif result.threshold == base.package_feed:
            self.out.write("%s/%s: %s" % (result.category, result.package,
                result.short_desc))
        elif result.threshold == base.category_feed:
            self.out.write("%s: %s" % (result.category, result.short_desc))
        else:
            self.out.write(result.short_desc)

    def finish(self):
        if not self.first_report:
            self.out.write()


class FancyReporter(base.Reporter):

    """
    grouped colored output, example:

    sys-apps/portage
      WrongIndentFound: sys-apps/portage-2.1-r2.ebuild has whitespace in indentation on line 169
      NonsolvableDeps: sys-apps/portage-2.1-r2: rdepends  ppc-macos: unsolvable default-darwin/macos/10.4, solutions: [ >=app-misc/pax-utils-0.1.13 ]
      StaleUnstableKeyword: sys-apps/portage-2.1-r2: no change in 75 days, keywords [ ~x86-fbsd ]
    """

    # default report, akin to repoman
    priority = 1

    def __init__(self, out):
        """Initialize.

        :type out: L{snakeoil.formatters.Formatter}.
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
        s = ''
        if result.threshold == base.versioned_feed:
            s = "version %s: " % result.version
        self.out.write(
            self.out.fg('yellow'), result.__class__.__name__, self.out.reset,
            ': ', s, result.short_desc)
        self.out.first_prefix.pop()
        self.out.later_prefix.pop()


class NullReporter(base.Reporter):

    """
    reporter used for timing tests; no output
    """

    priority = -10000000

    def __init__(self, out):
        pass

    def add_report(self, result):
        pass


class XmlReporter(base.Reporter):

    """
    dump an xml feed of reports
    """

    # xml report, shouldn't be used but in worst case.
    priority = -1000

    repo_template = "<result><msg>%s</msg></result>"
    cat_template = "<result><category>%(category)s</category><msg>%(msg)s</msg></result>"
    pkg_template = ("<result><category>%(category)s</category>"
        "<package>%(package)s</package><msg>%(msg)s</msg></result>")
    ver_template = ("<result><category>%(category)s</category>"
        "<package>%(package)s</package><version>%(version)s</version>"
        "<msg>%(msg)s</msg></result>")

    threshold_map = {
        base.repository_feed: repo_template,
        base.category_feed: cat_template,
        base.package_feed: pkg_template,
        base.versioned_feed: ver_template,
        base.ebuild_feed: ver_template,
    }

    def __init__(self, out):
        """Initialize.

        :type out: L{snakeoil.formatters.Formatter}.
        """
        base.Reporter.__init__(self)
        self.out = out

    def start(self):
        self.out.write('<checks>')

    def add_report(self, result):
        d = dict((k, getattr(result, k, '')) for k in
                 ("category", "package", "version"))
        d["msg"] = xml.escape(result.short_desc)
        self.out.write(self.threshold_map[result.threshold] % d)

    def finish(self):
        self.out.write('</checks>')


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
    @configurable({'dest': 'str'}, typename='pkgcheck_reporter_factory')
    def configurable_reporter_factory(dest=None):
        if dest is None:
            return klass
        def reporter_factory(out):
            try:
                f = open(dest, 'w')
            except EnvironmentError, e:
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
null_reporter = make_configurable_reporter_factory(NullReporter)
null_reporter.__name__ = 'null'


@configurable({'reporters': 'refs:pkgcheck_reporter_factory'},
              typename='pkgcheck_reporter_factory')
def multiplex_reporter(reporters):
    def make_multiplex_reporter(out):
        return MultiplexReporter(*list(factory(out) for factory in reporters))
    return make_multiplex_reporter
