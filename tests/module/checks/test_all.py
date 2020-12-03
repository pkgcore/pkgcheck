import pytest
from pkgcheck import objects, results
from pkgcheck import checks as checks_mod
from snakeoil.cli import arghparse

from ..misc import init_check


def test_checks():
    """Scan through all public checks and verify various aspects."""
    for name, cls in objects.CHECKS.items():
        assert cls.known_results, f"check class {name!r} doesn't define known results"


def test_check_scope(tool):
    """Verify check scopes match their source scopes."""
    namespace = arghparse.Namespace()
    # forcibly enable all checks so none are skipped
    namespace.forced_checks = [name for name, _cls in objects.CHECKS.items()]
    options, _func = tool.parse_args(['scan'], namespace)
    enabled_checks = checks_mod.init_checks(options.addons, options)
    for (source, is_async), runners in enabled_checks.items():
        for check in runners:
            assert check.scope == source.scope, \
                f"check scope doesn't match source scope: {check}"


def test_keywords():
    """Scan through all public result keywords and verify various aspects."""
    for name, cls in objects.KEYWORDS.items():
        assert cls.level is not None, f"result class {name!r} missing level"


class TestMetadataError:
    """Test MetadataError attribute registry."""

    def test_reregister_error(self):
        with pytest.raises(ValueError, match="metadata attribute 'eapi' already registered"):
            class InvalidEapi2(results.MetadataError, results.VersionResult):
                attr = 'eapi'

    def test_register_missing_attr(self):
        with pytest.raises(ValueError, match="class missing metadata attributes"):
            class InvalidAttr(results.MetadataError, results.VersionResult):
                pass


class TestGentooRepoCheck:

    def test_non_gentoo_repo(self, tool, make_repo):
        self.repo = make_repo()
        args = ['scan', '--repo', self.repo.location]
        options, _ = tool.parse_args(args)
        with pytest.raises(checks_mod.SkipCheck, match='not running against gentoo repo'):
            init_check(checks_mod.GentooRepoCheck, options)

    def test_gentoo_repo(self, tool, make_repo):
        self.repo = make_repo(repo_id='gentoo')
        args = ['scan', '--repo', self.repo.location]
        options, _ = tool.parse_args(args)
        assert init_check(checks_mod.GentooRepoCheck, options)


class TestOverlayCheck:

    def test_non_overlay_repo(self, tool, testconfig):
        tool.parser.set_defaults(override_config=testconfig)
        options, _ = tool.parse_args(['scan', '--repo', 'gentoo'])
        with pytest.raises(checks_mod.SkipCheck, match='not running against overlay'):
            init_check(checks_mod.OverlayRepoCheck, options)

    def test_overlay_repo(self, tool, testconfig):
        tool.parser.set_defaults(override_config=testconfig)
        options, _ = tool.parse_args(['scan', '--repo', 'overlay'])
        assert init_check(checks_mod.OverlayRepoCheck, options)


class TestGitCheck:

    @pytest.fixture(autouse=True)
    def _setup(self, tool, make_repo, make_git_repo):
        # initialize parent repo
        self.parent_git_repo = make_git_repo()
        self.parent_repo = make_repo(
            self.parent_git_repo.path, repo_id='gentoo', arches=['amd64'])
        self.parent_git_repo.add_all('initial commit')

        # initialize child repo
        self.child_git_repo = make_git_repo()
        self.child_git_repo.run(['git', 'remote', 'add', 'origin', self.parent_git_repo.path])
        self.child_git_repo.run(['git', 'pull', 'origin', 'master'])
        self.child_git_repo.run(['git', 'remote', 'set-head', 'origin', 'master'])
        self.child_repo = make_repo(self.child_git_repo.path)

    def test_no_commits_option(self, tool, make_git_repo):
        options, _ = tool.parse_args(
            ['scan', '--repo', self.child_repo.location])
        with pytest.raises(checks_mod.SkipCheck, match='not scanning against git commits'):
            init_check(checks_mod.GitCheck, options)

    def test_commits_option(self, tool, make_repo):
        self.child_repo.create_ebuild('cat/pkg-1')
        self.child_git_repo.add_all('cat/pkg-1')
        options, _ = tool.parse_args(
            ['scan', '--repo', self.child_repo.location, '--commits'])
        assert init_check(checks_mod.GitCheck, options)

    def test_no_local_commits(self, tool):
        with pytest.raises(SystemExit) as excinfo:
            tool.parse_args(['scan', '--repo', self.child_repo.location, '--commits'])
        assert excinfo.value.code == 0

        # parent repo has new commits
        self.parent_repo.create_ebuild('cat/pkg-1')
        self.parent_git_repo.add_all('cat/pkg-1')
        self.child_git_repo.run(['git', 'pull', 'origin', 'master'])
        with pytest.raises(SystemExit) as excinfo:
            tool.parse_args(['scan', '--repo', self.child_repo.location, '--commits'])
        assert excinfo.value.code == 0


class TestGitCacheCheck:

    def test_no_cache(self, tool):
        options, _ = tool.parse_args(['scan', '--cache', 'no'])
        with pytest.raises(checks_mod.SkipCheck, match='git cache support required'):
            init_check(checks_mod.GitCacheCheck, options)

    def test_cache(self, tool):
        options, _ = tool.parse_args(['scan'])
        assert init_check(checks_mod.GitCacheCheck, options)


class TestEclassCacheCheck:

    def test_no_cache(self, tool):
        options, _ = tool.parse_args(['scan', '--cache', 'no'])
        with pytest.raises(checks_mod.SkipCheck, match='eclass cache support required'):
            init_check(checks_mod.EclassCacheCheck, options)

    def test_cache(self, tool):
        options, _ = tool.parse_args(['scan'])
        assert init_check(checks_mod.EclassCacheCheck, options)


class TestNetworkCheck:

    def test_network_disabled(self, tool):
        options, _ = tool.parse_args(['scan'])
        with pytest.raises(checks_mod.SkipCheck, match='network checks not enabled'):
            init_check(checks_mod.NetworkCheck, options)

    def test_network_enabled(self, tool):
        options, _ = tool.parse_args(['scan', '--net'])
        assert init_check(checks_mod.NetworkCheck, options)
