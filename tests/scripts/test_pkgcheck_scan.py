import os
import shlex
import shutil
import subprocess
import tempfile
import textwrap
from collections import defaultdict
from functools import partial
from io import StringIO
from operator import attrgetter
from unittest.mock import patch

import pytest
from pkgcheck import __title__ as project
from pkgcheck import base
from pkgcheck import checks as checks_mod
from pkgcheck import const, objects, reporters, scan
from pkgcheck.scripts import run
from pkgcore import const as pkgcore_const
from pkgcore.ebuild import atom, restricts
from pkgcore.restrictions import packages
from snakeoil.contexts import chdir, os_environ
from snakeoil.fileutils import touch
from snakeoil.formatters import PlainTextFormatter
from snakeoil.osutils import pjoin

from ..misc import Profile


class TestPkgcheckScanParseArgs:
    def test_skipped_checks(self, tool):
        options, _ = tool.parse_args(["scan"])
        assert options.enabled_checks
        # some checks should always be skipped by default
        assert set(options.enabled_checks) != set(objects.CHECKS.values())

    def test_enabled_check(self, tool):
        options, _ = tool.parse_args(["scan", "-c", "PkgDirCheck"])
        assert options.enabled_checks == {checks_mod.pkgdir.PkgDirCheck}

    def test_disabled_check(self, tool):
        options, _ = tool.parse_args(["scan"])
        assert checks_mod.pkgdir.PkgDirCheck in options.enabled_checks
        options, _ = tool.parse_args(["scan", "-c=-PkgDirCheck"])
        assert options.enabled_checks
        assert checks_mod.pkgdir.PkgDirCheck not in options.enabled_checks

    def test_targets(self, tool):
        options, _ = tool.parse_args(["scan", "dev-util/foo"])
        assert list(options.restrictions) == [(base.package_scope, atom.atom("dev-util/foo"))]

    def test_stdin_targets(self, tool):
        with patch("sys.stdin", StringIO("dev-util/foo")):
            options, _ = tool.parse_args(["scan", "-"])
            assert list(options.restrictions) == [(base.package_scope, atom.atom("dev-util/foo"))]

    def test_invalid_targets(self, tool, capsys):
        with pytest.raises(SystemExit) as excinfo:
            options, _ = tool.parse_args(["scan", "dev-util/f$o"])
        assert excinfo.value.code == 2
        out, err = capsys.readouterr()
        err = err.strip()
        assert err == "pkgcheck scan: error: invalid package atom: 'dev-util/f$o'"

    def test_unknown_path_target(self, tool, capsys):
        with pytest.raises(SystemExit) as excinfo:
            tool.parse_args(["scan", "/foo/bar"])
        assert excinfo.value.code == 2
        out, err = capsys.readouterr()
        err = err.strip().split("\n")
        assert err[-1].startswith(
            "pkgcheck scan: error: 'standalone' repo doesn't contain: '/foo/bar'"
        )

    def test_target_repo_id(self, tool):
        options, _ = tool.parse_args(["scan", "standalone"])
        assert options.target_repo.repo_id == "standalone"
        assert list(options.restrictions) == [(base.repo_scope, packages.AlwaysTrue)]

    def test_target_dir_path(self, repo, tool):
        options, _ = tool.parse_args(["scan", repo.location])
        assert options.target_repo.repo_id == "fake"
        assert list(options.restrictions) == [(base.repo_scope, packages.AlwaysTrue)]

    def test_target_dir_path_in_repo(self, repo, tool):
        path = pjoin(repo.location, "profiles")
        options, _ = tool.parse_args(["scan", path])
        assert options.target_repo.repo_id == "fake"
        assert list(options.restrictions) == [(base.profiles_scope, packages.AlwaysTrue)]

    def test_target_dir_path_in_configured_repo(self, tool):
        options, _ = tool.parse_args(["scan", "standalone"])
        path = pjoin(options.target_repo.location, "profiles")
        options, _ = tool.parse_args(["scan", path])
        assert options.target_repo.repo_id == "standalone"
        assert list(options.restrictions) == [(base.profiles_scope, packages.AlwaysTrue)]

    def test_target_non_repo_path(self, tool, capsys, tmp_path):
        with pytest.raises(SystemExit) as excinfo:
            tool.parse_args(["scan", str(tmp_path)])
        assert excinfo.value.code == 2
        out, err = capsys.readouterr()
        assert not out
        assert err.startswith(
            f"pkgcheck scan: error: 'standalone' repo doesn't contain: '{str(tmp_path)}'"
        )

    def test_target_invalid_repo(self, tool, capsys, make_repo):
        repo = make_repo(masters=["unknown"])
        with pytest.raises(SystemExit) as excinfo:
            tool.parse_args(["scan", repo.location])
        assert excinfo.value.code == 2
        out, err = capsys.readouterr()
        assert not out
        err = err.strip()
        assert err.startswith("pkgcheck scan: error: repo init failed")
        assert err.endswith("has missing masters: 'unknown'")

    def test_target_file_path(self, repo, tool):
        os.makedirs(pjoin(repo.location, "dev-util", "foo"))
        ebuild_path = pjoin(repo.location, "dev-util", "foo", "foo-0.ebuild")
        touch(ebuild_path)
        options, _ = tool.parse_args(["scan", ebuild_path])
        restrictions = [
            restricts.CategoryDep("dev-util"),
            restricts.PackageDep("foo"),
            restricts.VersionMatch("=", "0"),
        ]
        assert list(options.restrictions) == [
            (base.version_scope, packages.AndRestriction(*restrictions))
        ]
        assert options.target_repo.repo_id == "fake"

    def test_target_package_dir_cwd(self, repo, tool):
        os.makedirs(pjoin(repo.location, "dev-util", "foo"))
        with chdir(pjoin(repo.location, "dev-util", "foo")):
            options, _ = tool.parse_args(["scan"])
            assert options.target_repo.repo_id == "fake"
            restrictions = [
                restricts.CategoryDep("dev-util"),
                restricts.PackageDep("foo"),
            ]
            assert list(options.restrictions) == [
                (base.package_scope, packages.AndRestriction(*restrictions))
            ]

    def test_target_repo_dir_cwd(self, repo, tool):
        with chdir(repo.location):
            options, _ = tool.parse_args(["scan"])
            assert options.target_repo.repo_id == "fake"
            assert list(options.restrictions) == [(base.repo_scope, packages.AlwaysTrue)]

    def test_unknown_repo(self, tmp_path, capsys, tool):
        for opt in ("-r", "--repo"):
            with pytest.raises(SystemExit) as excinfo:
                with chdir(str(tmp_path)):
                    options, _ = tool.parse_args(["scan", opt, "foo"])
            assert excinfo.value.code == 2
            out, err = capsys.readouterr()
            assert not out
            assert err.startswith(
                "pkgcheck scan: error: argument -r/--repo: couldn't find repo 'foo'"
            )

    def test_invalid_repo(self, tmp_path, capsys, tool):
        (tmp_path / "foo").touch()
        for opt in ("-r", "--repo"):
            with pytest.raises(SystemExit) as excinfo:
                with chdir(str(tmp_path)):
                    options, _ = tool.parse_args(["scan", opt, "foo"])
            assert excinfo.value.code == 2
            out, err = capsys.readouterr()
            assert not out
            assert err.startswith("pkgcheck scan: error: argument -r/--repo: repo init failed:")

    def test_valid_repo(self, tool):
        for opt in ("-r", "--repo"):
            options, _ = tool.parse_args(["scan", opt, "standalone"])
            assert options.target_repo.repo_id == "standalone"
            assert list(options.restrictions) == [(base.repo_scope, packages.AlwaysTrue)]

    def test_unknown_reporter(self, capsys, tool):
        for opt in ("-R", "--reporter"):
            with pytest.raises(SystemExit) as excinfo:
                options, _ = tool.parse_args(["scan", opt, "foo"])
            assert excinfo.value.code == 2
            out, err = capsys.readouterr()
            assert not out
            assert err.startswith("pkgcheck scan: error: no reporter matches 'foo'")

    def test_format_reporter(self, capsys, tool):
        # missing --format
        with pytest.raises(SystemExit) as excinfo:
            tool.parse_args(["scan", "-R", "FormatReporter"])
        assert excinfo.value.code == 2
        out, err = capsys.readouterr()
        err = err.strip().split("\n")
        assert err[-1].endswith("missing or empty --format option required by FormatReporter")

        # missing -R FormatReporter
        with pytest.raises(SystemExit) as excinfo:
            tool.parse_args(["scan", "--format", "foo"])
        assert excinfo.value.code == 2
        out, err = capsys.readouterr()
        err = err.strip().split("\n")
        assert err[-1].endswith("--format option is only valid when using FormatReporter")

        # properly set
        options, _ = tool.parse_args(["scan", "-R", "FormatReporter", "--format", "foo"])

    def test_cwd(self, capsys, tool):
        # regularly working
        options, _ = tool.parse_args(["scan"])
        assert options.cwd == os.getcwd()

        # pretend the CWD was removed out from under us
        with patch("os.getcwd") as getcwd:
            getcwd.side_effect = FileNotFoundError("CWD is gone")
            options, _ = tool.parse_args(["scan"])
            assert options.cwd == const.DATA_PATH

    def test_eclass_target(self, fakerepo, tool):
        (eclass_dir := fakerepo / "eclass").mkdir()
        (eclass_path := eclass_dir / "foo.eclass").touch()
        options, _ = tool.parse_args(["scan", str(eclass_path)])
        assert list(options.restrictions) == [(base.eclass_scope, "foo")]

    def test_profiles_target(self, fakerepo, tool):
        profiles_path = str(fakerepo / "profiles")
        options, _ = tool.parse_args(["scan", profiles_path])
        assert list(options.restrictions) == [(base.profiles_scope, packages.AlwaysTrue)]

    def test_profiles_path_target_file(self, fakerepo, tool):
        (pkg_mask_path := fakerepo / "profiles/package.mask").touch()
        options, _ = tool.parse_args(["scan", str(pkg_mask_path)])
        assert list(options.restrictions) == [(base.profile_node_scope, str(pkg_mask_path))]

    def test_profiles_path_target_dir(self, fakerepo, tool):
        (profile_dir := fakerepo / "profiles/default").mkdir(parents=True)
        (pkg_mask_path := profile_dir / "package.mask").touch()
        (pkg_use_path := profile_dir / "package.use").touch()
        options, _ = tool.parse_args(["scan", str(profile_dir)])
        assert list(options.restrictions) == [
            (base.profile_node_scope, {str(pkg_mask_path), str(pkg_use_path)})
        ]

    def test_no_default_repo(self, tool, capsys):
        stubconfig = pjoin(pkgcore_const.DATA_PATH, "stubconfig")
        with pytest.raises(SystemExit) as excinfo:
            tool.parse_args(["--config", stubconfig, "scan"])
        assert excinfo.value.code == 2
        out, err = capsys.readouterr()
        assert not out
        assert err.strip() == "pkgcheck scan: error: no default repo found"

    @pytest.mark.parametrize(
        ("makeopts", "expected_jobs"),
        (
            ("", 4),
            ("-j1", 1),
            ("--jobs=6 -l 1", 6),
            ("--load 1", 4),
        ),
    )
    def test_makeopts_parsing(self, parser, makeopts, expected_jobs):
        with patch("os.cpu_count", return_value=4), os_environ(MAKEOPTS=makeopts):
            options = parser.parse_args(["scan"])
            assert options.jobs == expected_jobs
            assert options.tasks == 5 * expected_jobs

    def test_no_color(self, parser, tmp_path):
        (config_file := tmp_path / "config").write_text(
            textwrap.dedent(
                """\
                    [DEFAULT]
                    color = true
                """
            )
        )

        args = ("scan", "--config", str(config_file))
        with os_environ("NO_COLOR"):
            assert parser.parse_args(args).color is True
        with os_environ(NO_COLOR="1"):
            # NO_COLOR overrides config file
            assert parser.parse_args(args).color is False
            # cmd line option overrides NO_COLOR
            assert parser.parse_args([*args, "--color", "n"]).color is False
            assert parser.parse_args([*args, "--color", "y"]).color is True


class TestPkgcheckScanParseConfigArgs:
    @pytest.fixture(autouse=True)
    def _setup(self, parser, tmp_path, repo):
        self.parser = parser
        self.repo = repo
        self.args = ["scan", "-r", repo.location]
        self.system_config = str(tmp_path / "system-config")
        self.user_config = str(tmp_path / "user-config")
        self.config = str(tmp_path / "custom-config")

    def test_config_precedence(self):
        configs = [self.system_config, self.user_config]
        with patch("pkgcheck.cli.ConfigFileParser.default_configs", configs):
            with open(self.system_config, "w") as f:
                f.write(
                    textwrap.dedent(
                        """\
                            [DEFAULT]
                            jobs=1000
                        """
                    )
                )
            options = self.parser.parse_args(self.args)
            assert options.jobs == 1000

            # user config overrides system config
            with open(self.user_config, "w") as f:
                f.write(
                    textwrap.dedent(
                        """\
                            [DEFAULT]
                            jobs=1001
                        """
                    )
                )
            options = self.parser.parse_args(self.args)
            assert options.jobs == 1001

            # repo config overrides user config
            with open(pjoin(self.repo.location, "metadata", "pkgcheck.conf"), "w") as f:
                f.write(
                    textwrap.dedent(
                        """\
                            [DEFAULT]
                            jobs=1002
                        """
                    )
                )
            options = self.parser.parse_args(self.args)
            assert options.jobs == 1002

            # custom config overrides user config
            with open(self.config, "w") as f:
                f.write(
                    textwrap.dedent(
                        """\
                            [DEFAULT]
                            jobs=1003
                        """
                    )
                )
            config_args = self.args + ["--config", self.config]
            options = self.parser.parse_args(config_args)
            assert options.jobs == 1003

            # repo defaults override general defaults
            with open(self.config, "a") as f:
                f.write(
                    textwrap.dedent(
                        f"""\
                            [{self.repo.repo_id}]
                            jobs=1004
                        """
                    )
                )
            options = self.parser.parse_args(config_args)
            assert options.jobs == 1004

            # command line options override all config settings
            options = self.parser.parse_args(config_args + ["--jobs", "9999"])
            assert options.jobs == 9999


class TestPkgcheckScan:
    script = staticmethod(partial(run, project))

    repos_data = pytest.REPO_ROOT / "testdata/data/repos"
    repos_dir = pytest.REPO_ROOT / "testdata/repos"
    repos = tuple(sorted(x.name for x in repos_data.iterdir() if x.name != "network"))

    _all_results = [
        (cls, result)
        for name, cls in sorted(objects.CHECKS.items())
        if not issubclass(cls, checks_mod.NetworkCheck)
        for result in sorted(cls.known_results, key=attrgetter("__name__"))
    ]

    @pytest.fixture(autouse=True)
    def _setup(self, testconfig, tmp_path):
        self.cache_dir = str(tmp_path)
        base_args = ["--config", testconfig]
        self.scan = partial(scan, base_args=base_args)
        # args for running `pkgcheck scan` via API call
        self.scan_args = ["--config", "no", "--cache-dir", self.cache_dir]
        # args for running pkgcheck like a script
        self.args = [project] + base_args + ["scan"] + self.scan_args

    def test_empty_repo(self, capsys, repo):
        with patch("sys.argv", self.args + [repo.location]):
            with pytest.raises(SystemExit) as excinfo:
                self.script()
            assert excinfo.value.code == 0
            out, err = capsys.readouterr()
            assert out == err == ""

    def test_no_matching_checks_scope(self, tool):
        options, _ = tool.parse_args(["scan", "standalone"])
        path = pjoin(options.target_repo.location, "profiles")
        error = "no matching checks available for profiles scope"
        with pytest.raises(base.PkgcheckUserException, match=error):
            self.scan(self.scan_args + ["-c", "PkgDirCheck", path])

    def test_stdin_targets_with_no_args(self):
        with patch("sys.stdin", StringIO()):
            with pytest.raises(base.PkgcheckUserException, match="no targets"):
                self.scan(self.scan_args + ["-"])

    def test_exit_status(self, repo):
        # create good ebuild and another with an invalid EAPI
        repo.create_ebuild("newcat/pkg-0")
        repo.create_ebuild("newcat/pkg-1", eapi="-1")
        # exit status isn't enabled by default
        args = ["-r", repo.location]
        with patch("sys.argv", self.args + args):
            with pytest.raises(SystemExit) as excinfo:
                self.script()
            assert excinfo.value.code == 0

        # all error level results are flagged by default when enabled
        with patch("sys.argv", self.args + args + ["--exit"]):
            with pytest.raises(SystemExit) as excinfo:
                self.script()
            assert excinfo.value.code == 1

        # selective error results will only flag those specified
        with patch("sys.argv", self.args + args + ["--exit", "InvalidSlot"]):
            with pytest.raises(SystemExit) as excinfo:
                self.script()
            assert excinfo.value.code == 0
        with patch("sys.argv", self.args + args + ["--exit", "InvalidEapi"]):
            with pytest.raises(SystemExit) as excinfo:
                self.script()
            assert excinfo.value.code == 1

    def test_filter_latest(self, make_repo):
        repo = make_repo(arches=["amd64"])
        # create stub profile to suppress ArchesWithoutProfiles result
        repo.create_profiles([Profile("stub", "amd64")])
        # create ebuild with unknown keywords
        repo.create_ebuild("cat/pkg-0", keywords=["unknown"], homepage="https://example.com")
        # and a good ebuild for the latest version
        repo.create_ebuild("cat/pkg-1", keywords=["amd64"], homepage="https://example.com")

        # results for old pkgs will be shown by default
        args = ["-r", repo.location]
        with patch("sys.argv", self.args + args):
            results = list(self.scan(self.scan_args + args))
            assert len(results) == 1

        # but are ignored when running using the 'latest' filter
        for opt in ("-f", "--filter"):
            for arg in ("latest", "latest:KeywordsCheck", "latest:UnknownKeywords"):
                assert not list(self.scan(self.scan_args + args + [opt, arg]))

    def test_scan_restrictions(self, repo):
        # create two ebuilds with bad EAPIs
        repo.create_ebuild("cat/pkg-0", eapi="-1")
        repo.create_ebuild("cat/pkg-1", eapi="-1")

        # matching version restriction returns a single result
        results = list(self.scan(self.scan_args + ["-r", repo.location, "=cat/pkg-0"]))
        assert [x.version for x in results] == ["0"]

        # unmatching version restriction returns no results
        results = list(self.scan(self.scan_args + ["-r", repo.location, "=cat/pkg-2"]))
        assert not results

        # matching package restriction returns two sorted results
        results = list(self.scan(self.scan_args + ["-r", repo.location, "cat/pkg"]))
        assert [x.version for x in results] == ["0", "1"]

        # unmatching package restriction returns no results
        results = list(self.scan(self.scan_args + ["-r", repo.location, "cat/unknown"]))
        assert not results

    def test_scan_quiet(self, repo):
        # create an ebuild referencing variable in homepage
        repo.create_ebuild("cat/pkg-0", homepage="https://example.com/${PN}")

        # in non-quiet mode, the result is shown
        results = list(self.scan(self.scan_args + ["-r", repo.location]))
        assert len(results) == 1

        # in quiet mode, the result is suppressed
        for arg in ("-q", "--quiet"):
            results = list(self.scan(self.scan_args + ["-r", repo.location, arg]))
            assert not results

        results = list(
            self.scan(self.scan_args + ["-r", repo.location, "-q", "-k=-UnknownKeywords"])
        )
        assert not results

    def test_explict_skip_check(self):
        """SkipCheck exceptions are raised when triggered for explicitly enabled checks."""
        error = "network checks not enabled"
        with pytest.raises(base.PkgcheckException, match=error):
            self.scan(self.scan_args + ["-C", "net"])

    def test_cache_disabled_skip_check(self):
        """SkipCheck exceptions are raised when enabled checks require disabled cache types."""
        args = ["--cache=-git", "-c", "StableRequestCheck"]
        error = "StableRequestCheck: git cache support required"
        with pytest.raises(base.PkgcheckException, match=error):
            self.scan(self.scan_args + args)

    @pytest.mark.parametrize(
        "module",
        (
            pytest.param("pkgcheck.pipeline.UnversionedSource", id="producer"),
            pytest.param("pkgcheck.runners.SyncCheckRunner.run", id="consumer"),
        ),
    )
    def test_pipeline_exceptions(self, module):
        """Test checkrunner pipeline against unhandled exceptions."""
        with patch(module) as faked:
            faked.side_effect = Exception("pipeline failed")
            with pytest.raises(base.PkgcheckException, match="Exception: pipeline failed"):
                list(self.scan(self.scan_args))

    # nested mapping of repos to checks/keywords they cover
    _checks = defaultdict(lambda: defaultdict(set))

    @pytest.mark.parametrize("repo", repos)
    def test_scan_repo_data(self, repo):
        """Make sure the test data is up to date check/result naming wise."""
        for check in (self.repos_data / repo).iterdir():
            assert check.name in objects.CHECKS
            for keyword in check.iterdir():
                assert keyword.name in objects.KEYWORDS
                self._checks[repo][check.name].add(keyword.name)

    @staticmethod
    def _script(fix, repo_path):
        try:
            subprocess.run([fix], cwd=repo_path, capture_output=True, check=True, text=True)
        except subprocess.CalledProcessError as exc:
            error = exc.stderr if exc.stderr else exc.stdout
            pytest.fail(error)

    def _scan_results(self, repo, tmp_path, verbosity):
        """Scan a target repo, saving results for verification."""
        repo_dir = self.repos_dir / repo

        # run all existing triggers
        triggers = [
            pjoin(root, "trigger.sh")
            for root, _dirs, files in os.walk(self.repos_data / repo)
            if "trigger.sh" in files
        ]
        if triggers:
            triggered_repo = tmp_path / f"triggered-{repo}"
            shutil.copytree(repo_dir, triggered_repo)
            for trigger in triggers:
                self._script(trigger, triggered_repo)
            repo_dir = triggered_repo

        if repo not in self._checks:
            self.test_scan_repo_data(repo)
        args = (["-v"] * verbosity) + ["-r", str(repo_dir), "-c", ",".join(self._checks[repo])]

        # add any defined extra repo args
        try:
            args.extend(shlex.split((repo_dir / "metadata/pkgcheck-args").read_text()))
        except FileNotFoundError:
            pass

        results = []
        for result in self.scan(self.scan_args + args):
            # ignore results generated from stubs
            if any(getattr(result, x, "").startswith("stub") for x in ("category", "package")):
                continue
            results.append(result)

        results_set = set(results)
        assert len(results) == len(results_set)
        return results_set

    def _get_results(self, path: str):
        """Return the set of result objects from a given json stream file."""
        try:
            with (self.repos_data / path).open() as f:
                return set(reporters.JsonStream.from_iter(f))
        except FileNotFoundError:
            return set()

    def _render_results(self, results, **kwargs):
        """Render a given set of result objects into their related string form."""
        with tempfile.TemporaryFile() as f:
            with reporters.FancyReporter(out=PlainTextFormatter(f), **kwargs) as reporter:
                for result in sorted(results):
                    reporter.report(result)
            f.seek(0)
            output = f.read().decode()
            return output

    @pytest.mark.parametrize("repo", repos)
    def test_scan_repo(self, repo, tmp_path_factory):
        """Run pkgcheck against test pkgs in bundled repo, verifying result output."""
        results = set()
        verbose_results = set()
        scan_results = self._scan_results(repo, tmp_path_factory.mktemp("scan"), verbosity=0)
        scan_verbose_results = self._scan_results(repo, tmp_path_factory.mktemp("ver"), verbosity=1)
        for check, keywords in self._checks[repo].items():
            for keyword in keywords:
                # verify the expected results were seen during the repo scans
                expected_results = self._get_results(f"{repo}/{check}/{keyword}/expected.json")
                assert expected_results, "regular results must always exist"
                assert self._render_results(expected_results), "failed rendering results"
                results.update(expected_results)

                # when expected verbose results exist use them, otherwise fallback to using the regular ones
                expected_verbose_results = self._get_results(
                    f"{repo}/{check}/{keyword}/expected-verbose.json"
                )
                if expected_verbose_results:
                    assert self._render_results(
                        expected_verbose_results
                    ), "failed rendering verbose results"
                    verbose_results.update(expected_verbose_results)
                else:
                    verbose_results.update(expected_results)

        if results != scan_results:
            missing = self._render_results(results - scan_results)
            unknown = self._render_results(scan_results - results)
            error = ["unmatched repo scan results:\n\n"]
            if missing:
                error.append(f"{repo} repo missing expected results:\n{missing}")
            if unknown:
                error.append(f"{repo} repo unknown results:\n{unknown}")
            pytest.fail("\n".join(error), pytrace=False)
        if verbose_results != scan_verbose_results:
            missing = self._render_results(verbose_results - scan_verbose_results)
            unknown = self._render_results(scan_verbose_results - verbose_results)
            error = ["unmatched verbose repo scan results:\n\n"]
            if missing:
                error.append(f"{repo} repo missing expected results:\n{missing}")
            if unknown:
                error.append(f"{repo} repo unknown results:\n{unknown}")
            pytest.fail("\n".join(error), pytrace=False)

    @staticmethod
    def _patch(fix, repo_path):
        with fix.open() as fix_file:
            try:
                subprocess.run(
                    ["patch", "-p1"],
                    cwd=repo_path,
                    stdin=fix_file,
                    capture_output=True,
                    check=True,
                    text=True,
                )
            except subprocess.CalledProcessError as exc:
                error = exc.stderr if exc.stderr else exc.stdout
                pytest.fail(error)

    @pytest.mark.parametrize("check, result", _all_results)
    def test_fix(self, check, result, tmp_path):
        """Apply fixes to pkgs, verifying the related results are fixed."""
        check_name = check.__name__
        keyword = result.__name__
        tested = False
        for repo in self.repos:
            keyword_dir = self.repos_data / repo / check_name / keyword
            if (fix := keyword_dir / "fix.patch").exists():
                func = self._patch
            elif (fix := keyword_dir / "fix.sh").exists():
                func = self._script
            else:
                continue

            # apply a fix if one exists and make sure the related result doesn't appear
            repo_dir = self.repos_dir / repo
            fixed_repo = tmp_path / f"fixed-{repo}"
            shutil.copytree(repo_dir, fixed_repo)
            func(fix, fixed_repo)

            args = ["-r", str(fixed_repo), "-c", check_name, "-k", keyword]

            # add any defined extra repo args
            try:
                with open(f"{repo_dir}/metadata/pkgcheck-args") as f:
                    args.extend(shlex.split(f.read()))
            except FileNotFoundError:
                pass

            results = list(self.scan(self.scan_args + args))
            if results:
                error = ["unexpected repo scan results:\n"]
                error.append(self._render_results(results))
                pytest.fail("\n".join(error), pytrace=False)

            shutil.rmtree(fixed_repo)
            tested = True

        if not tested:
            pytest.skip("fix not available")
