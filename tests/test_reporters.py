import json
import sys
import typing
from textwrap import dedent

import pytest
from pkgcore.test.misc import FakePkg
from snakeoil.formatters import PlainTextFormatter

from pkgcheck import base, reporters
from pkgcheck.checks import codingstyle, git, metadata, metadata_xml, pkgdir, profiles


class BaseReporter:
    reporter_cls: type[reporters.Reporter]
    add_report_output: typing.ClassVar[str]
    pkg = FakePkg("dev-libs/foo-0")

    results: typing.Final = (
        profiles.ProfileWarning(Exception("profile warning")),
        profiles.ProfileError(Exception("profile error")),
        git.InvalidCommitMessage("no commit message", commit="8d86269bb4c7"),
        metadata_xml.CatMissingMetadataXml("metadata.xml", pkg=pkg),
        pkgdir.InvalidPN(("bar", "baz"), pkg=pkg),
        metadata.BadFilename(("0.tar.gz", "foo.tar.gz"), pkg=pkg),
        codingstyle.ReadonlyVariable("P", line="P=6", lineno=7, pkg=pkg),
        codingstyle.EbuildUnquotedVariable("D", lines=(5, 7), pkg=pkg),
    )

    def mk_reporter(self, *args, **kwargs) -> reporters.Reporter:
        out = PlainTextFormatter(sys.stdout)
        return self.reporter_cls(out, *args, **kwargs)

    def assert_add_report(self, capsys, reporter: reporters.Reporter, expected_out: str) -> None:
        if reporter is None:
            reporter = self.mk_reporter()
        with reporter as report:
            for result in self.results:
                report(result)
        out, err = capsys.readouterr()
        assert not err
        assert out == expected_out

    def test_add_report(self, capsys):
        self.assert_add_report(capsys, self.mk_reporter(), self.add_report_output)


class TestStrReporter(BaseReporter):
    reporter_cls = reporters.StrReporter
    add_report_output = dedent(
        """\
            profile warning
            profile error
            commit 8d86269bb4c7: no commit message
            dev-libs: category is missing metadata.xml
            dev-libs/foo: invalid package names: [ bar, baz ]
            dev-libs/foo-0: bad filenames: [ 0.tar.gz, foo.tar.gz ]
            dev-libs/foo-0: read-only variable 'P' assigned, line 7: P=6
            dev-libs/foo-0: unquoted variable D on lines: 5, 7
        """
    )


class TestFancyReporter(BaseReporter):
    reporter_cls = reporters.FancyReporter
    add_report_output = dedent(
        """\
            profiles
              ProfileWarning: profile warning
              ProfileError: profile error

            commit
              InvalidCommitMessage: commit 8d86269bb4c7: no commit message

            dev-libs
              CatMissingMetadataXml: category is missing metadata.xml

            dev-libs/foo
              InvalidPN: invalid package names: [ bar, baz ]
              BadFilename: version 0: bad filenames: [ 0.tar.gz, foo.tar.gz ]
              ReadonlyVariable: version 0: read-only variable 'P' assigned, line 7: P=6
              UnquotedVariable: version 0: unquoted variable D on lines: 5, 7
        """
    )


class TestJsonReporter(BaseReporter):
    reporter_cls = reporters.JsonReporter

    add_report_output = dedent(
        """\
            {"_warning": {"ProfileWarning": "profile warning"}}
            {"_error": {"ProfileError": "profile error"}}
            {"_style": {"InvalidCommitMessage": "commit 8d86269bb4c7: no commit message"}}
            {"dev-libs": {"_error": {"CatMissingMetadataXml": "category is missing metadata.xml"}}}
            {"dev-libs": {"foo": {"_error": {"InvalidPN": "invalid package names: [ bar, baz ]"}}}}
            {"dev-libs": {"foo": {"0": {"_warning": {"BadFilename": "bad filenames: [ 0.tar.gz, foo.tar.gz ]"}}}}}
            {"dev-libs": {"foo": {"0": {"_warning": {"ReadonlyVariable": "read-only variable 'P' assigned, line 7: P=6"}}}}}
            {"dev-libs": {"foo": {"0": {"_warning": {"UnquotedVariable": "unquoted variable D on lines: 5, 7"}}}}}
        """
    )


class TestXmlReporter(BaseReporter):
    reporter_cls = reporters.XmlReporter
    add_report_output = dedent(
        """\
            <checks>
            <result><class>ProfileWarning</class><msg>profile warning</msg></result>
            <result><class>ProfileError</class><msg>profile error</msg></result>
            <result><class>InvalidCommitMessage</class><msg>commit 8d86269bb4c7: no commit message</msg></result>
            <result><category>dev-libs</category><class>CatMissingMetadataXml</class><msg>category is missing metadata.xml</msg></result>
            <result><category>dev-libs</category><package>foo</package><class>InvalidPN</class><msg>invalid package names: [ bar, baz ]</msg></result>
            <result><category>dev-libs</category><package>foo</package><version>0</version><class>BadFilename</class><msg>bad filenames: [ 0.tar.gz, foo.tar.gz ]</msg></result>
            <result><category>dev-libs</category><package>foo</package><version>0</version><class>ReadonlyVariable</class><msg>read-only variable 'P' assigned, line 7: P=6</msg></result>
            <result><category>dev-libs</category><package>foo</package><version>0</version><class>UnquotedVariable</class><msg>unquoted variable D on lines: 5, 7</msg></result>
            </checks>
        """
    )


class TestCsvReporter(BaseReporter):
    reporter_cls = reporters.CsvReporter
    add_report_output = dedent(
        """\
            ,,,profile warning
            ,,,profile error
            ,,,commit 8d86269bb4c7: no commit message
            dev-libs,,,category is missing metadata.xml
            dev-libs,foo,,"invalid package names: [ bar, baz ]"
            dev-libs,foo,0,"bad filenames: [ 0.tar.gz, foo.tar.gz ]"
            dev-libs,foo,0,"read-only variable 'P' assigned, line 7: P=6"
            dev-libs,foo,0,"unquoted variable D on lines: 5, 7"
        """
    )


class TestFormatReporter(BaseReporter):
    reporter_cls = reporters.FormatReporter

    def mk_reporter(self, format_str: str, *args, **kwargs) -> reporters.FormatReporter:
        out = PlainTextFormatter(sys.stdout)
        return self.reporter_cls(format_str, out, *args, **kwargs)

    @pytest.mark.parametrize(
        ["format_str", "expected"],
        [
            ("r", "r\n" * len(BaseReporter.results)),
            ("{category}", "dev-libs\n" * 5),
            ("{category}/{package}", "/\n/\n/\ndev-libs/\n" + "dev-libs/foo\n" * 4),
            (
                "{category}/{package}-{version}",
                "/-\n/-\n/-\ndev-libs/-\ndev-libs/foo-\n" + "dev-libs/foo-0\n" * 3,
            ),
            ("{name}", "\n".join(result.name for result in BaseReporter.results) + "\n"),
            ("{foo}", ""),
        ],
    )
    def test_add_report(self, capsys, format_str: str, expected: str):  # pyright: ignore[reportIncompatibleMethodOverride]
        self.assert_add_report(capsys, self.mk_reporter(format_str), expected)

    def test_unsupported_index(self, capsys):
        with self.mk_reporter("{0}") as report:
            with pytest.raises(base.PkgcheckUserException) as excinfo:
                report(self.results[0])
            assert "integer indexes are not supported" in str(excinfo.value)


class TestJsonStream(BaseReporter):
    reporter_cls: type[reporters.JsonStream] = reporters.JsonStream  # pyright: ignore[reportIncompatibleVariableOverride]

    add_report_output = dedent(
        """\
            {"__class__": "ProfileWarning", "msg": "profile warning"}
            {"__class__": "ProfileError", "msg": "profile error"}
            {"__class__": "InvalidCommitMessage", "commit": "8d86269bb4c7", "error": "no commit message"}
            {"__class__": "CatMissingMetadataXml", "category": "dev-libs", "filename": "metadata.xml"}
            {"__class__": "InvalidPN", "category": "dev-libs", "package": "foo", "ebuilds": ["bar", "baz"]}
            {"__class__": "BadFilename", "category": "dev-libs", "package": "foo", "version": "0", "filenames": ["0.tar.gz", "foo.tar.gz"]}
            {"__class__": "ReadonlyVariable", "category": "dev-libs", "package": "foo", "version": "0", "line": "P=6", "lineno": 7, "variable": "P"}
            {"__class__": "EbuildUnquotedVariable", "category": "dev-libs", "package": "foo", "version": "0", "lines": [5, 7], "variable": "D"}
            """
    )

    def test_from_iter(self):
        assert self.results == tuple(
            self.reporter_cls.from_iter(x for x in self.add_report_output.split("\n") if x.strip())
        )

    def test_deserialize_error(self):
        # deserializing non-result objects raises exception
        obj = self.reporter_cls.to_json(["result"])
        with pytest.raises(reporters.DeserializationError, match="failed loading"):
            next(self.reporter_cls.from_iter([obj]))

        # deserializing mangled JSON result objects raises exception
        # TODO: remove typing.cast once to_json is refactored to use registered decoders.
        obj = typing.cast(dict[str, str], self.reporter_cls.to_json(self.results[0]))
        del obj["__class__"]
        json_obj = json.dumps(obj)
        with pytest.raises(reporters.DeserializationError, match="unknown result"):
            next(self.reporter_cls.from_iter([json_obj]))


class TestFlycheckReporter(BaseReporter):
    reporter_cls = reporters.FlycheckReporter
    add_report_output = dedent(
        """\
            -.ebuild:0:warning:ProfileWarning: profile warning
            -.ebuild:0:error:ProfileError: profile error
            -.ebuild:0:style:InvalidCommitMessage: commit 8d86269bb4c7: no commit message
            -.ebuild:0:error:CatMissingMetadataXml: category is missing metadata.xml
            foo-.ebuild:0:error:InvalidPN: invalid package names: [ bar, baz ]
            foo-0.ebuild:0:warning:BadFilename: bad filenames: [ 0.tar.gz, foo.tar.gz ]
            foo-0.ebuild:7:warning:ReadonlyVariable: read-only variable 'P' assigned, line 7: P=6
            foo-0.ebuild:5:warning:UnquotedVariable: unquoted variable D
            foo-0.ebuild:7:warning:UnquotedVariable: unquoted variable D
            """
    )
