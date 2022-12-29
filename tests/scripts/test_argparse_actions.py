import argparse
import random
import textwrap
from unittest.mock import patch

import pytest
from pkgcheck import base, checks, objects
from pkgcheck.scripts import argparse_actions
from pkgcheck.addons.caches import CachedAddon
from snakeoil.cli import arghparse


class TestConfigArg:
    @pytest.fixture(autouse=True)
    def _create_argparser(self):
        self.parser = arghparse.ArgumentParser()
        self.parser.add_argument("--config", action=argparse_actions.ConfigArg)

    def test_none(self):
        options = self.parser.parse_args([])
        assert options.config is None

    def test_enabled(self):
        for arg in ("config_file", "/path/to/config/file"):
            options = self.parser.parse_args(["--config", arg])
            assert options.config == arg

    def test_disabled(self):
        for arg in ("False", "false", "No", "no", "N", "n"):
            options = self.parser.parse_args(["--config", arg])
            assert options.config is False


class TestFilterArgs:
    @pytest.fixture(autouse=True)
    def _create_argparser(self):
        self.parser = arghparse.ArgumentParser()
        self.parser.set_defaults(config_checksets={"cset": ["StableRequestCheck"]})
        self.parser.add_argument("--filter", action=argparse_actions.FilterArgs)

    def test_none(self):
        options = self.parser.parse_args([])
        assert options.filter is None

    def test_unknown_filter(self, capsys):
        for arg in ("foo", "foo:PkgDirCheck"):
            with pytest.raises(SystemExit) as excinfo:
                self.parser.parse_args(["--filter", arg])
            out, err = capsys.readouterr()
            assert not out
            assert "unknown filter: 'foo'" in err
            assert excinfo.value.code == 2

    def test_disabled(self):
        for arg in ("False", "false", "No", "no", "N", "n"):
            options = self.parser.parse_args(["--filter", arg])
            assert options.filter == {}

    def test_enabled(self):
        for arg in ("latest", "latest:StableRequest", "latest:StableRequestCheck", "latest:cset"):
            options = self.parser.parse_args(["--filter", arg])
            assert objects.KEYWORDS["StableRequest"] in options.filter

    def test_unknown_value(self, capsys):
        with pytest.raises(SystemExit) as excinfo:
            self.parser.parse_args(["--filter", "latest:foo"])
        out, err = capsys.readouterr()
        assert not out
        assert "unknown checkset, check, or keyword: 'foo'" in err
        assert excinfo.value.code == 2


class TestCacheNegations:
    @pytest.fixture(autouse=True)
    def _create_argparser(self):
        self.parser = arghparse.ArgumentParser()
        self.parser.add_argument("--cache", action=argparse_actions.CacheNegations)
        self.caches = [x.type for x in CachedAddon.caches.values()]

    def test_defaults(self):
        options = self.parser.parse_args([])
        assert options.cache == dict(argparse_actions.CacheNegations.caches)

    def test_unknown(self, capsys):
        with pytest.raises(SystemExit) as excinfo:
            self.parser.parse_args(["--cache", "foo"])
        out, err = capsys.readouterr()
        assert not out
        assert "unknown cache type: 'foo'" in err
        assert excinfo.value.code == 2

    def test_all(self):
        for arg in ("True", "true", "Yes", "yes", "Y", "y"):
            options = self.parser.parse_args(["--cache", arg])
            for k, v in options.cache.items():
                assert v is True

    def test_none(self):
        for arg in ("False", "false", "No", "no", "N", "n"):
            options = self.parser.parse_args(["--cache", arg])
            for k, v in options.cache.items():
                assert v is False

    def test_enabled(self):
        cache = self.caches[random.randrange(len(self.caches))]
        options = self.parser.parse_args(["--cache", cache])
        for k, v in options.cache.items():
            if k == cache:
                assert v is True
            else:
                assert v is False

    def test_disabled(self):
        cache = self.caches[random.randrange(len(self.caches))]
        options = self.parser.parse_args([f"--cache=-{cache}"])
        for k, v in options.cache.items():
            if k == cache:
                assert v is False
            else:
                assert v is True


class TestChecksetArgs:
    @pytest.fixture(autouse=True)
    def _setup(self, tool, tmp_path):
        self.tool = tool
        self.cache_dir = str(tmp_path / ".cache")
        self.config = str(tmp_path / "config")
        self.args = ["scan", "--cache-dir", self.cache_dir]

    def test_unknown(self, capsys):
        for opt in ("-C", "--checksets"):
            with pytest.raises(SystemExit) as excinfo:
                self.tool.parse_args(self.args + [opt, "foo"])
            out, err = capsys.readouterr()
            assert not out
            assert "unknown checkset: 'foo'" in err
            assert excinfo.value.code == 2

    def test_aliases(self):
        for opt in ("-C", "--checksets"):
            # net
            options, _ = self.tool.parse_args(self.args + [opt, "net"])
            network_checks = [
                c for c, v in objects.CHECKS.items() if issubclass(v, checks.NetworkCheck)
            ]
            assert options.selected_checks == set(network_checks)

            # all
            options, _ = self.tool.parse_args(self.args + [opt, "all"])
            assert options.selected_checks == set(objects.CHECKS)

    def test_sets(self, capsys):
        with open(self.config, "w") as f:
            f.write(
                textwrap.dedent(
                    """\
                        [CHECKSETS]
                        set1=StableRequest
                        set2=-StableRequest
                        set3=SourcingCheck,-InvalidEapi,-InvalidSlot
                        bad=foo
                    """
                )
            )
        configs = [self.config]
        with patch("pkgcheck.cli.ConfigFileParser.default_configs", configs):
            for opt in ("-C", "--checksets"):
                # enabled keyword
                for arg in ("set1", "-set2"):
                    options, _ = self.tool.parse_args(self.args + [f"{opt}={arg}"])
                    assert options.filtered_keywords == {objects.KEYWORDS["StableRequest"]}
                    assert options.enabled_checks == {objects.CHECKS["StableRequestCheck"]}

                # disabled keyword
                for arg in ("-set1", "set2"):
                    options, _ = self.tool.parse_args(self.args + [f"{opt}={arg}"])
                    assert objects.KEYWORDS["StableRequest"] not in options.filtered_keywords

                # check/keywords mixture
                options, _ = self.tool.parse_args(self.args + [f"{opt}=set3"])
                assert options.filtered_keywords == {objects.KEYWORDS["SourcingError"]}
                assert options.enabled_checks == {objects.CHECKS["SourcingCheck"]}

                # unknown value
                with pytest.raises(SystemExit) as excinfo:
                    self.tool.parse_args(self.args + [f"{opt}=bad"])
                out, err = capsys.readouterr()
                assert not out
                assert "'bad' checkset, unknown check or keyword: 'foo'" in err
                assert excinfo.value.code == 2


class TestScopeArgs:
    @pytest.fixture(autouse=True)
    def _setup(self, tool, tmp_path):
        self.tool = tool
        self.cache_dir = str(tmp_path)
        self.args = ["scan", "--cache-dir", self.cache_dir]

    def test_unknown_scope(self, capsys):
        for opt in ("-s", "--scopes"):
            with pytest.raises(SystemExit) as excinfo:
                options, _ = self.tool.parse_args(self.args + [opt, "foo"])
            assert excinfo.value.code == 2
            out, err = capsys.readouterr()
            err = err.strip().split("\n")
            assert "unknown scope: 'foo'" in err[-1]

    def test_missing_scope(self, capsys):
        for opt in ("-s", "--scopes"):
            with pytest.raises(SystemExit) as excinfo:
                options, _ = self.tool.parse_args(self.args + [opt])
            assert excinfo.value.code == 2
            out, err = capsys.readouterr()
            err = err.strip().split("\n")
            assert err[0] == ("pkgcheck scan: error: argument -s/--scopes: expected one argument")

    def test_disabled(self):
        options, _ = self.tool.parse_args(self.args + ["--scopes=-eclass"])
        assert options.selected_scopes == frozenset()

    def test_enabled(self):
        options, _ = self.tool.parse_args(self.args + ["--scopes", "repo"])
        assert options.selected_scopes == frozenset([base.scopes["repo"]])


class TestCheckArgs:
    @pytest.fixture(autouse=True)
    def _setup(self, tool, tmp_path):
        self.tool = tool
        self.cache_dir = str(tmp_path)
        self.args = ["scan", "--cache-dir", self.cache_dir]

    def test_unknown_check(self, capsys):
        for opt in ("-c", "--checks"):
            with pytest.raises(SystemExit) as excinfo:
                options, _ = self.tool.parse_args(self.args + [opt, "foo"])
            assert excinfo.value.code == 2
            out, err = capsys.readouterr()
            err = err.strip().split("\n")
            assert "unknown check: 'foo'" in err[-1]

    def test_token_errors(self):
        for opt in ("-c", "--checks"):
            for operation in ("-", "+"):
                with pytest.raises(argparse.ArgumentTypeError) as excinfo:
                    options, _ = self.tool.parse_args(self.args + [f"{opt}={operation}"])
                assert "without a token" in str(excinfo.value)

    def test_missing_check(self, capsys):
        for opt in ("-c", "--checks"):
            with pytest.raises(SystemExit) as excinfo:
                options, _ = self.tool.parse_args(self.args + [opt])
            assert excinfo.value.code == 2
            out, err = capsys.readouterr()
            err = err.strip().split("\n")
            assert err[0] == ("pkgcheck scan: error: argument -c/--checks: expected one argument")

    def test_neutral(self):
        for opt in ("-c", "--checks"):
            options, _ = self.tool.parse_args(self.args + [opt, "UnusedLicensesCheck"])
            assert options.selected_checks == frozenset(["UnusedLicensesCheck"])

    def test_subtractive(self):
        for opt in ("-c", "--checks"):
            check = list(objects.CHECKS)[random.randrange(len(objects.CHECKS))]
            options, _ = self.tool.parse_args(self.args + [f"{opt}=-{check}"])
            assert options.selected_checks == frozenset()

    def test_additive(self):
        for opt in ("-c", "--checks"):
            options, _ = self.tool.parse_args(self.args)
            assert issubclass(checks.perl.PerlCheck, checks.OptionalCheck)
            assert checks.perl.PerlCheck not in set(options.enabled_checks)
            options, _ = self.tool.parse_args(self.args + [f"{opt}=+PerlCheck"])
            assert checks.perl.PerlCheck in set(options.enabled_checks)
            assert options.selected_checks == frozenset(["PerlCheck"])


class TestKeywordArgs:
    @pytest.fixture(autouse=True)
    def _setup(self, tool, tmp_path):
        self.tool = tool
        self.cache_dir = str(tmp_path)
        self.args = ["scan", "--cache-dir", self.cache_dir]

    def test_unknown_keyword(self, capsys):
        for opt in ("-k", "--keywords"):
            with pytest.raises(SystemExit) as excinfo:
                options, _ = self.tool.parse_args(self.args + [opt, "foo"])
            assert excinfo.value.code == 2
            out, err = capsys.readouterr()
            err = err.strip().split("\n")
            assert "unknown keyword: 'foo'" in err[-1]

    def test_missing_keyword(self, capsys):
        for opt in ("-k", "--keywords"):
            with pytest.raises(SystemExit) as excinfo:
                options, _ = self.tool.parse_args(self.args + [opt])
            assert excinfo.value.code == 2
            out, err = capsys.readouterr()
            err = err.strip().split("\n")
            assert err[0] == ("pkgcheck scan: error: argument -k/--keywords: expected one argument")

    def test_enabled(self):
        for opt in ("-k", "--keywords"):
            options, _ = self.tool.parse_args(self.args + [opt, "UnusedLicenses"])
            assert options.selected_keywords == frozenset(["UnusedLicenses"])
            assert options.filtered_keywords == frozenset([objects.KEYWORDS["UnusedLicenses"]])
            assert options.enabled_checks == {checks.repo_metadata.UnusedLicensesCheck}

    def test_disabled_check(self):
        """Disabling all keywords for a given check also disables the check."""
        for opt in ("-k", "--keywords"):
            default_checks = set(objects.CHECKS.default.values())
            default_keywords = set().union(*(v.known_results for v in default_checks))
            keyword = checks.repo_metadata.UnusedLicenses
            check = checks.repo_metadata.UnusedLicensesCheck
            assert check in default_checks
            assert check.known_results == frozenset([keyword])
            options, _ = self.tool.parse_args(self.args + [f"{opt}=-UnusedLicenses"])
            assert options.selected_keywords == frozenset()
            assert options.filtered_keywords == frozenset(default_keywords - {keyword})
            assert check not in set(options.enabled_checks)

    def test_disabled(self):
        for opt in ("-k", "--keywords"):
            default_keywords = set().union(
                *(v.known_results for v in objects.CHECKS.default.values())
            )
            keyword_cls = list(default_keywords)[random.randrange(len(default_keywords))]
            keyword = keyword_cls.__name__
            options, _ = self.tool.parse_args(self.args + [f"{opt}=-{keyword}"])
            assert options.selected_keywords == frozenset()
            assert options.filtered_keywords == frozenset(default_keywords - {keyword_cls})

    def test_aliases(self):
        for opt in ("-k", "--keywords"):
            for alias in ("error", "warning", "info"):
                options, _ = self.tool.parse_args(self.args + [opt, alias])
                alias_keywords = list(getattr(objects.KEYWORDS, alias))
                assert options.selected_keywords == frozenset(alias_keywords)


class TestExitArgs:
    @pytest.fixture(autouse=True)
    def _setup(self, tool, tmp_path):
        self.tool = tool
        self.cache_dir = str(tmp_path)
        self.args = ["scan", "--cache-dir", self.cache_dir]

    def test_unknown(self, capsys):
        with pytest.raises(SystemExit) as excinfo:
            self.tool.parse_args(self.args + ["--exit", "foo"])
        out, err = capsys.readouterr()
        assert not out
        assert "unknown checkset, check, or keyword: 'foo'" in err
        assert excinfo.value.code == 2

    def test_none(self):
        options, _ = self.tool.parse_args(self.args)
        assert options.exit_keywords == ()

    def test_default(self):
        options, _ = self.tool.parse_args(self.args + ["--exit"])
        assert options.exit_keywords == frozenset(objects.KEYWORDS.error.values())

    def test_enabled(self):
        keyword = list(objects.KEYWORDS)[random.randrange(len(objects.KEYWORDS))]
        objs = (objects.KEYWORDS[x] for x in objects.KEYWORDS.aliases.get(keyword, [keyword]))
        options, _ = self.tool.parse_args(self.args + ["--exit", keyword])
        assert options.exit_keywords == frozenset(objs)

    def test_disabled(self):
        keyword = list(objects.KEYWORDS)[random.randrange(len(objects.KEYWORDS))]
        objs = (objects.KEYWORDS[x] for x in objects.KEYWORDS.aliases.get(keyword, [keyword]))
        options, _ = self.tool.parse_args(self.args + [f"--exit=-{keyword}"])
        assert options.exit_keywords == frozenset(objects.KEYWORDS.error.values()) - frozenset(objs)

    def test_aliases(self):
        for alias in ("error", "warning", "info"):
            options, _ = self.tool.parse_args(self.args + [f"--exit={alias}"])
            assert options.exit_keywords == frozenset(getattr(objects.KEYWORDS, alias).values())
