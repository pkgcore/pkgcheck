import sys

from snakeoil.formatters import PlainTextFormatter

from pkgcheck import base, reporters
from pkgcheck.checks.profiles import ProfileWarning, ProfileError


class BaseReporter(object):

    reporter_cls = base.Reporter

    def mk_reporter(self, **kwargs):
        out = PlainTextFormatter(sys.stdout)
        reporter = self.reporter_cls(out=out, **kwargs)
        self.log_warning = ProfileWarning('profile warning')
        self.log_error = ProfileError('profile error')
        return reporter

    @property
    def add_report_output(self):
        raise NotImplementedError

    @property
    def filtered_report_output(self):
        raise NotImplementedError

    def test_add_report(self, capsys):
        self.reporter = self.mk_reporter()
        self.reporter.start()
        self.reporter.report(self.log_warning)
        self.reporter.finish()
        out, err = capsys.readouterr()
        assert not err
        assert out == self.add_report_output

    def test_filtered_report(self, capsys):
        self.reporter = self.mk_reporter(keywords=(ProfileError,))
        self.reporter.start()
        self.reporter.report(self.log_warning)
        self.reporter.report(self.log_error)
        self.reporter.finish()
        out, err = capsys.readouterr()
        assert not err
        assert out == self.filtered_report_output


class TestStrReporter(BaseReporter):

    reporter_cls = reporters.StrReporter
    add_report_output = """\nprofile warning\n\n"""
    filtered_report_output = """\nprofile error\n\n"""


class TestFancyReporter(BaseReporter):

    reporter_cls = reporters.FancyReporter
    add_report_output = """
repo
  ProfileWarning: profile warning
"""
    filtered_report_output = """
repo
  ProfileError: profile error
"""


class TestNullReporter(BaseReporter):

    reporter_cls = reporters.NullReporter
    add_report_output = ""
    filtered_report_output = ""


class TestJsonReporter(BaseReporter):

    reporter_cls = reporters.JsonReporter
    add_report_output = """{"_warning": {"ProfileWarning": ["profile warning"]}}\n"""
    filtered_report_output = """{"_error": {"ProfileError": ["profile error"]}}\n"""


class TestXmlReporter(BaseReporter):

    reporter_cls = reporters.XmlReporter
    add_report_output = """<checks>\n<result><class>ProfileWarning</class><msg>profile warning</msg></result>\n</checks>\n"""
    filtered_report_output = """<checks>\n<result><class>ProfileError</class><msg>profile error</msg></result>\n</checks>\n"""
