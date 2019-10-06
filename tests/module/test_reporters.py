import pickle
import sys
from functools import partial
from textwrap import dedent

from pkgcore.test.misc import FakePkg
import pytest
from snakeoil.formatters import PlainTextFormatter

from pkgcheck import base, reporters, results
from pkgcheck.checks import pkgdir, profiles, metadata, metadata_xml


class BaseReporter(object):

    reporter_cls = reporters.Reporter

    @pytest.fixture(autouse=True)
    def _setup(self):
        self.log_warning = profiles.ProfileWarning('profile warning')
        self.log_error = profiles.ProfileError('profile error')
        pkg = FakePkg('dev-libs/foo-0')
        self.category_result = metadata_xml.CatMissingMetadataXml('metadata.xml', pkg=pkg)
        self.package_result = pkgdir.InvalidPN(('bar', 'baz'), pkg=pkg)
        self.versioned_result = metadata.BadFilename(('0.tar.gz', 'foo.tar.gz'), pkg=pkg)

    def mk_reporter(self, **kwargs):
        out = PlainTextFormatter(sys.stdout)
        return self.reporter_cls(out, **kwargs)

    add_report_output = None
    filtered_report_output = None

    def test_add_report(self, capsys):
        with self.mk_reporter() as reporter:
            reporter.report(self.log_warning)
            reporter.report(self.category_result)
            reporter.report(self.package_result)
            reporter.report(self.versioned_result)
        out, err = capsys.readouterr()
        assert not err
        assert out == self.add_report_output

    def test_filtered_report(self, capsys):
        with self.mk_reporter(keywords=(profiles.ProfileError,)) as reporter:
            reporter.report(self.log_warning)
            reporter.report(self.log_error)
        out, err = capsys.readouterr()
        assert not err
        assert out == self.filtered_report_output


class TestStrReporter(BaseReporter):

    reporter_cls = reporters.StrReporter
    add_report_output = dedent("""\
        profile warning
        dev-libs: category is missing metadata.xml
        dev-libs/foo: invalid package names: [ bar, baz ]
        dev-libs/foo-0: bad filenames: [ 0.tar.gz, foo.tar.gz ]
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
          InvalidPN: invalid package names: [ bar, baz ]
          BadFilename: version 0: bad filenames: [ 0.tar.gz, foo.tar.gz ]
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
        {"dev-libs": {"foo": {"_error": {"InvalidPN": ["invalid package names: [ bar, baz ]"]}}}}
        {"dev-libs": {"foo": {"0": {"_warning": {"BadFilename": ["bad filenames: [ 0.tar.gz, foo.tar.gz ]"]}}}}}
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
        <result><category>dev-libs</category><package>foo</package><class>InvalidPN</class><msg>invalid package names: [ bar, baz ]</msg></result>
        <result><category>dev-libs</category><package>foo</package><version>0</version><class>BadFilename</class><msg>bad filenames: [ 0.tar.gz, foo.tar.gz ]</msg></result>
        </checks>
    """)
    filtered_report_output = dedent("""\
        <checks>
        <result><class>ProfileError</class><msg>profile error</msg></result>
        </checks>
    """)


class TestCsvReporter(BaseReporter):

    reporter_cls = reporters.CsvReporter
    add_report_output = dedent("""\
        ,,,profile warning
        dev-libs,,,category is missing metadata.xml
        dev-libs,foo,,"invalid package names: [ bar, baz ]"
        dev-libs,foo,0,"bad filenames: [ 0.tar.gz, foo.tar.gz ]"
    """)
    filtered_report_output = """,,,profile error\n"""


class TestFormatReporter(BaseReporter):

    def test_add_report(self, capsys):
        for format_str, expected in (
                    ('r', 'r\n' * 4),
                    ('{category}', 'dev-libs\n' * 3),
                    ('{category}/{package}', 'dev-libs/foo\n' * 2),
                    ('{category}/{package}-{version}', 'dev-libs/foo-0\n'),
                    ('{foo}', ''),
                ):
            self.reporter_cls = partial(reporters.FormatReporter, format_str)
            self.add_report_output = expected
            super().test_add_report(capsys)

    def test_filtered_report(self, capsys):
        for format_str, expected in (
                    ('r', 'r\n'),
                    ('{category}', ''),
                    ('{category}/{package}', ''),
                    ('{category}/{package}-{version}', ''),
                    ('{foo}', ''),
                    ('{desc}', 'profile error\n'),
                ):
            self.reporter_cls = partial(reporters.FormatReporter, format_str)
            self.filtered_report_output = expected
            super().test_filtered_report(capsys)


class UnPickleableResult(results.Result):

    def __init__(self):
        self.func = lambda x: x


class TestPickleStream(BaseReporter):

    reporter_cls = reporters.PickleStream

    def test_add_report(self, capsysbinary):
        with self.mk_reporter() as reporter:
            for result in (self.log_warning, self.log_error, self.category_result,
                           self.package_result, self.versioned_result):
                reporter.report(result)
                out, err = capsysbinary.readouterr()
                assert not err
                unpickled_result = pickle.loads(out)
                assert str(unpickled_result) == str(result)

    def test_filtered_report(self, capsysbinary):
        with self.mk_reporter(keywords=(profiles.ProfileError,)) as reporter:
            reporter.report(self.log_warning)
            reporter.report(self.log_error)
        out, err = capsysbinary.readouterr()
        assert not err
        result = pickle.loads(out)
        assert str(result) == str(self.log_error)

    def test_unpickleable_result(self):
        result = UnPickleableResult()
        with self.mk_reporter() as reporter:
            with pytest.raises(TypeError):
                reporter.report(result)


class TestBinaryPickleStream(TestPickleStream):

    reporter_cls = reporters.BinaryPickleStream


class TestJsonStream(BaseReporter):

    reporter_cls = reporters.JsonStream

    def test_add_report(self, capsys):
        with self.mk_reporter() as reporter:
            for result in (self.log_warning, self.log_error, self.category_result,
                        self.package_result, self.versioned_result):
                reporter.report(result)
                out, err = capsys.readouterr()
                assert not err
                deserialized_result = reporter.from_json(out)
                assert str(deserialized_result) == str(result)

    def test_filtered_report(self, capsys):
        with self.mk_reporter(keywords=(profiles.ProfileError,)) as reporter:
            reporter.report(self.log_warning)
            reporter.report(self.log_error)
            out, err = capsys.readouterr()
            assert not err
            result = reporter.from_json(out)
            assert str(result) == str(self.log_error)
