import pickle
import sys
from textwrap import dedent

from pkgcore.test.misc import FakePkg
import pytest
from snakeoil.formatters import PlainTextFormatter

from pkgcheck import base, reporters
from pkgcheck.checks import pkgdir, profiles, metadata, metadata_xml


class BaseReporter(object):

    reporter_cls = base.Reporter

    def mk_reporter(self, **kwargs):
        out = PlainTextFormatter(sys.stdout)
        reporter = self.reporter_cls(out=out, **kwargs)
        self.log_warning = profiles.ProfileWarning('profile warning')
        self.log_error = profiles.ProfileError('profile error')
        pkg = FakePkg('dev-libs/foo-0')
        self.category_result = metadata_xml.CatMissingMetadataXml('metadata.xml', pkg=pkg)
        self.package_result = pkgdir.InvalidPN(('foo',), pkg=pkg)
        self.versioned_result = metadata.BadFilename(('0.tar.gz',), pkg=pkg)
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
        self.reporter.report(self.category_result)
        self.reporter.report(self.package_result)
        self.reporter.report(self.versioned_result)
        self.reporter.finish()
        out, err = capsys.readouterr()
        assert not err
        assert out == self.add_report_output

    def test_filtered_report(self, capsys):
        self.reporter = self.mk_reporter(keywords=(profiles.ProfileError,))
        self.reporter.start()
        self.reporter.report(self.log_warning)
        self.reporter.report(self.log_error)
        self.reporter.finish()
        out, err = capsys.readouterr()
        assert not err
        assert out == self.filtered_report_output


class TestStrReporter(BaseReporter):

    reporter_cls = reporters.StrReporter
    add_report_output = dedent("""\
        profile warning
        dev-libs: category is missing metadata.xml
        dev-libs/foo: invalid package name: [ foo ]
        dev-libs/foo-0: bad filename: [ 0.tar.gz ]
    """)
    filtered_report_output = """profile error\n"""


class TestFancyReporter(BaseReporter):

    reporter_cls = reporters.FancyReporter
    add_report_output = dedent("""\
        repo
          ProfileWarning: profile warning

        dev-libs
          CatMissingMetadataXml: category is missing metadata.xml

        dev-libs/foo
          InvalidPN: invalid package name: [ foo ]
          BadFilename: version 0: bad filename: [ 0.tar.gz ]
    """)
    filtered_report_output = dedent("""\
        repo
          ProfileError: profile error
    """)


class TestNullReporter(BaseReporter):

    reporter_cls = reporters.NullReporter
    add_report_output = ""
    filtered_report_output = ""


class TestJsonReporter(BaseReporter):

    reporter_cls = reporters.JsonReporter
    add_report_output = dedent("""\
        {"_warning": {"ProfileWarning": ["profile warning"]}}
        {"dev-libs": {"_error": {"CatMissingMetadataXml": ["category is missing metadata.xml"]}}}
        {"dev-libs": {"foo": {"_error": {"InvalidPN": ["invalid package name: [ foo ]"]}}}}
        {"dev-libs": {"foo": {"0": {"_warning": {"BadFilename": ["bad filename: [ 0.tar.gz ]"]}}}}}
    """)
    filtered_report_output = dedent("""\
        {"_error": {"ProfileError": ["profile error"]}}
    """)


class TestXmlReporter(BaseReporter):

    reporter_cls = reporters.XmlReporter
    add_report_output = dedent("""\
        <checks>
        <result><class>ProfileWarning</class><msg>profile warning</msg></result>
        <result><category>dev-libs</category><class>CatMissingMetadataXml</class><msg>category is missing metadata.xml</msg></result>
        <result><category>dev-libs</category><package>foo</package><class>InvalidPN</class><msg>invalid package name: [ foo ]</msg></result>
        <result><category>dev-libs</category><package>foo</package><version>0</version><class>BadFilename</class><msg>bad filename: [ 0.tar.gz ]</msg></result>
        </checks>
    """)
    filtered_report_output = dedent("""\
        <checks>
        <result><class>ProfileError</class><msg>profile error</msg></result>
        </checks>
    """)


class UnPickleableResult(base.Result):

    def __init__(self):
        self.func = lambda x: x


class TestPickleStream(BaseReporter):

    reporter_cls = reporters.PickleStream

    def test_add_report(self, capsysbinary):
        self.reporter = self.mk_reporter()
        for result in (self.log_warning, self.log_error, self.category_result,
                       self.package_result, self.versioned_result):
            self.reporter.start()
            self.reporter.report(result)
            self.reporter.finish()
            out, err = capsysbinary.readouterr()
            assert not err
            unpickled_result = pickle.loads(out)
            assert str(unpickled_result) == str(result)

    def test_filtered_report(self, capsysbinary):
        self.reporter = self.mk_reporter(keywords=(profiles.ProfileError,))
        self.reporter.start()
        self.reporter.report(self.log_warning)
        self.reporter.report(self.log_error)
        self.reporter.finish()
        out, err = capsysbinary.readouterr()
        assert not err
        result = pickle.loads(out)
        assert str(result) == str(self.log_error)

    def test_unpickleable_result(self):
        result = UnPickleableResult()
        reporter = self.mk_reporter()
        with pytest.raises(TypeError):
            reporter.start()
            reporter.report(result)
            reporter.finish()


class TestBinaryPickleStream(TestPickleStream):

    reporter_cls = reporters.BinaryPickleStream


class TestJsonStream(BaseReporter):

    reporter_cls = reporters.JsonStream

    def test_add_report(self, capsys):
        self.reporter = self.mk_reporter()
        for result in (self.log_warning, self.log_error, self.category_result,
                       self.package_result, self.versioned_result):
            self.reporter.start()
            self.reporter.report(result)
            self.reporter.finish()
            out, err = capsys.readouterr()
            assert not err
            deserialized_result = self.reporter.from_json(out)
            assert str(deserialized_result) == str(result)

    def test_filtered_report(self, capsys):
        self.reporter = self.mk_reporter(keywords=(profiles.ProfileError,))
        self.reporter.start()
        self.reporter.report(self.log_warning)
        self.reporter.report(self.log_error)
        self.reporter.finish()
        out, err = capsys.readouterr()
        assert not err
        result = self.reporter.from_json(out)
        assert str(result) == str(self.log_error)
