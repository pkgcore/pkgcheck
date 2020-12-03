import os
import subprocess
from unittest.mock import Mock, patch

import pytest
from pkgcore.ebuild.atom import atom as atom_cls
from pkgcore.restrictions import packages
from pkgcheck import base, git
from snakeoil.cli.exceptions import UserException
from snakeoil.fileutils import touch
from snakeoil.osutils import pjoin
from snakeoil.process import CommandNotFound, find_binary


# skip testing module if git isn't installed
try:
    find_binary('git')
except CommandNotFound:
    pytestmark = pytest.mark.skipif(True, reason='git not installed')


class TestPkgcheckScanCommitsParseArgs:

    @pytest.fixture(autouse=True)
    def _setup(self, tool):
        self.tool = tool
        self.args = ['scan']

    def test_commits_with_targets(self, capsys):
        with pytest.raises(SystemExit) as excinfo:
            options, _func = self.tool.parse_args(self.args + ['--commits', 'ref', 'dev-util/foo'])
        assert excinfo.value.code == 2
        out, err = capsys.readouterr()
        err = err.strip().split('\n')
        assert err[-1].startswith(
            "pkgcheck scan: error: --commits is mutually exclusive with target: dev-util/foo")

    def test_commits_git_unavailable(self, capsys):
        with patch('subprocess.run') as git_diff:
            git_diff.side_effect = FileNotFoundError
            with pytest.raises(SystemExit) as excinfo:
                options, _func = self.tool.parse_args(self.args + ['--commits'])
            assert excinfo.value.code == 2
            out, err = capsys.readouterr()
            err = err.strip().split('\n')
            assert err[-1].startswith(
                "pkgcheck scan: error: git not available to determine targets for --commits")

    def test_git_error(self, capsys):
        with patch('subprocess.run') as git_diff:
            git_diff.side_effect = subprocess.CalledProcessError(1, 'git')
            git_diff.side_effect.stderr = 'git error: foobar'
            with pytest.raises(SystemExit) as excinfo:
                options, _func = self.tool.parse_args(self.args + ['--commits'])
            assert excinfo.value.code == 2
            out, err = capsys.readouterr()
            err = err.strip().split('\n')
            assert err[-1].startswith('pkgcheck scan: error: failed running git: ')

    def test_commits_nonexistent(self):
        with patch('subprocess.run') as git_diff:
            git_diff.return_value.stdout = ''
            with pytest.raises(SystemExit) as excinfo:
                options, _func = self.tool.parse_args(self.args + ['--commits'])
            assert excinfo.value.code == 0

    def test_commits_existing(self):
        output = [
            'dev-libs/foo/metadata.xml\n',
            'media-libs/bar/bar-0.ebuild\n',
        ]
        with patch('subprocess.run') as git_diff:
            git_diff.return_value.stdout = ''.join(output)
            options, _func = self.tool.parse_args(self.args + ['--commits'])
            atom_restricts = [atom_cls('dev-libs/foo'), atom_cls('media-libs/bar')]
            assert list(options.restrictions) == \
                [(base.package_scope, packages.OrRestriction(*atom_restricts))]

    def test_commits_eclasses(self):
        output = [
            'dev-libs/foo/metadata.xml\n',
            'media-libs/bar/bar-0.ebuild\n',
            'eclass/foo.eclass\n',
        ]
        with patch('subprocess.run') as git_diff:
            git_diff.return_value.stdout = ''.join(output)
            options, _func = self.tool.parse_args(self.args + ['--commits'])
            atom_restricts = [atom_cls('dev-libs/foo'), atom_cls('media-libs/bar')]
            restrictions = list(options.restrictions)
            assert len(restrictions) == 2
            assert restrictions[0] == \
                (base.package_scope, packages.OrRestriction(*atom_restricts))
            assert restrictions[1][0] == base.eclass_scope
            assert restrictions[1][1].match(['foo'])

    def test_commits_ignored_changes(self):
        output = [
            'foo/bar.txt\n',
            'eclass/tests/check.sh\n',
        ]
        with patch('subprocess.run') as git_diff:
            git_diff.return_value.stdout = ''.join(output)
            with pytest.raises(SystemExit) as excinfo:
                self.tool.parse_args(self.args + ['--commits'])
            assert excinfo.value.code == 0


class TestGitStash:

    def test_non_git_repo(self, tmp_path):
        with pytest.raises(ValueError, match='not a git repo'):
            with git.GitStash(str(tmp_path)):
                pass

    def test_empty_git_repo(self, git_repo):
        with git.GitStash(git_repo.path):
            pass

    def test_untracked_file(self, git_repo):
        path = pjoin(git_repo.path, 'foo')
        touch(path)
        assert os.path.exists(path)
        with git.GitStash(git_repo.path):
            assert not os.path.exists(path)
        assert os.path.exists(path)

    def test_failed_stashing(self, git_repo):
        path = pjoin(git_repo.path, 'foo')
        touch(path)
        assert os.path.exists(path)
        with patch('subprocess.run') as run:
            err = subprocess.CalledProcessError(1, 'git stash')
            err.stderr = 'git stash failed'
            run.side_effect = [Mock(stdout='foo'), err]
            with pytest.raises(UserException, match='git failed stashing files'):
                with git.GitStash(git_repo.path):
                    pass

    def test_failed_unstashing(self, git_repo):
        path = pjoin(git_repo.path, 'foo')
        touch(path)
        assert os.path.exists(path)
        with pytest.raises(UserException, match='git failed applying stash'):
            with git.GitStash(git_repo.path):
                assert not os.path.exists(path)
                touch(path)


class TestParsedGitRepo:

    def test_non_git(self, tmp_path):
        p = git.ParsedGitRepo(str(tmp_path))
        with pytest.raises(git.GitError, match='failed running git log'):
            list(p.parse_git_log('HEAD', commits=True))

    def test_empty_repo(self, make_git_repo):
        git_repo = make_git_repo()
        p = git.ParsedGitRepo(git_repo.path)
        with pytest.raises(git.GitError, match='failed running git log'):
            list(p.parse_git_log('HEAD', commits=True))

    def test_commits_parsing(self, make_repo, make_git_repo):
        git_repo = make_git_repo()
        repo = make_repo(git_repo.path)

        # make an initial commit
        git_repo.add('foo', msg='foo', create=True)
        p = git.ParsedGitRepo(git_repo.path)
        commits = list(p.parse_git_log('HEAD', commits=True))
        assert len(commits) == 1
        assert commits[0].message == ['foo']
        assert commits[0].pkgs == ()
        orig_commit = commits[0]

        # make another commit
        git_repo.add('bar', msg='bar', create=True)
        commits = list(p.parse_git_log('HEAD', commits=True))
        assert len(commits) == 2
        assert commits[0].message == ['bar']
        assert commits[0].pkgs == ()
        assert commits[1] == orig_commit
        assert len(set(commits)) == 2

        # make a pkg commit
        repo.create_ebuild('cat/pkg-0')
        git_repo.add_all('cat/pkg-0')
        commits = list(p.parse_git_log('HEAD', commits=True))
        assert len(commits) == 3
        assert commits[0].message == ['cat/pkg-0']
        assert commits[0].pkgs == (atom_cls('=cat/pkg-0'),)

        # make a multiple pkg commit
        repo.create_ebuild('cat/new1-0')
        repo.create_ebuild('cat/new2-0')
        git_repo.add_all('cat: various updates')
        commits = list(p.parse_git_log('HEAD', commits=True))
        assert len(commits) == 4
        assert commits[0].message == ['cat: various updates']
        assert commits[0].pkgs == (atom_cls('=cat/new1-0'), atom_cls('=cat/new2-0'))

    def test_pkgs_parsing(self, repo, make_git_repo):
        git_repo = make_git_repo(repo.location, commit=True)
        p = git.ParsedGitRepo(git_repo.path)

        # initialize the dict cache
        data = p.update('HEAD')
        assert data == {}

        # overlay repo objects on top of the dict cache
        changed_repo = git.GitChangedRepo(data)
        assert len(changed_repo) == 0
        modified_repo = git.GitModifiedRepo(data)
        assert len(modified_repo) == 0
        added_repo = git.GitAddedRepo(data)
        assert len(added_repo) == 0
        removed_repo = git.GitRemovedRepo(data)
        assert len(removed_repo) == 0

        # create a pkg and commit it
        repo.create_ebuild('cat/pkg-0')
        git_repo.add_all('cat/pkg-0')
        pkgs = list(p.parse_git_log('HEAD'))
        assert len(pkgs) == 1
        pkg = pkgs[0]
        assert pkg.atom == atom_cls('=cat/pkg-0')
        assert pkg.status == 'A'

        # update the dict cache
        p.update('HEAD', data=data)
        commit = git_repo.HEAD

        # overlay repo objects on top of the dict cache
        changed_repo = git.GitChangedRepo(data)
        assert len(changed_repo) == 1
        modified_repo = git.GitModifiedRepo(data)
        assert len(modified_repo) == 1
        added_repo = git.GitAddedRepo(data)
        assert len(added_repo) == 1
        removed_repo = git.GitRemovedRepo(data)
        assert len(removed_repo) == 0

        # add a new version and commit it
        repo.create_ebuild('cat/pkg-1')
        git_repo.add_all('cat/pkg-1')
        pkgs = list(p.parse_git_log('HEAD'))
        assert len(pkgs) == 2
        pkg = pkgs[0]
        assert pkg.atom == atom_cls('=cat/pkg-1')
        assert pkg.status == 'A'

        # update the dict cache
        p.update(f'{commit}..HEAD', data=data)
        commit = git_repo.HEAD

        # overlay repo objects on top of the dict cache
        changed_repo = git.GitChangedRepo(data)
        assert len(changed_repo) == 2
        modified_repo = git.GitModifiedRepo(data)
        assert len(modified_repo) == 2
        added_repo = git.GitAddedRepo(data)
        assert len(added_repo) == 2
        removed_repo = git.GitRemovedRepo(data)
        assert len(removed_repo) == 0

        # remove the old version
        git_repo.remove('cat/pkg/pkg-0.ebuild')
        pkgs = list(p.parse_git_log('HEAD'))
        assert len(pkgs) == 3
        pkg = pkgs[0]
        assert pkg.atom == atom_cls('=cat/pkg-0')
        assert pkg.status == 'D'

        # update the dict cache
        p.update(f'{commit}..HEAD', data=data)
        commit = git_repo.HEAD

        # overlay repo objects on top of the dict cache
        changed_repo = git.GitChangedRepo(data)
        assert len(changed_repo) == 3
        modified_repo = git.GitModifiedRepo(data)
        assert len(modified_repo) == 2
        added_repo = git.GitAddedRepo(data)
        assert len(added_repo) == 2
        removed_repo = git.GitRemovedRepo(data)
        assert len(removed_repo) == 1

        # rename the pkg
        git_repo.move('cat', 'cat2')
        pkgs = list(p.parse_git_log('HEAD'))
        assert len(pkgs) == 5
        new_pkg, old_pkg = pkgs[:2]
        assert old_pkg.atom == atom_cls('=cat/pkg-1')
        assert old_pkg.status == 'D'
        assert new_pkg.atom == atom_cls('=cat2/pkg-1')
        assert new_pkg.status == 'A'

        # update the dict cache
        p.update(f'{commit}..HEAD', data=data)
        commit = git_repo.HEAD

        # overlay repo objects on top of the dict cache
        changed_repo = git.GitChangedRepo(data)
        assert len(changed_repo) == 5
        modified_repo = git.GitModifiedRepo(data)
        assert len(modified_repo) == 3
        added_repo = git.GitAddedRepo(data)
        assert len(added_repo) == 3
        removed_repo = git.GitRemovedRepo(data)
        assert len(removed_repo) == 2


class TestGitAddon:

    @pytest.fixture(autouse=True)
    def _setup(self, tool, tmp_path, repo):
        self.repo = repo
        self.cache_dir = str(tmp_path)

        args = ['scan', '--cache-dir', self.cache_dir, '--repo', self.repo.location]
        options, _ = tool.parse_args(args)
        self.addon = git.GitAddon(options)
        self.cache_file = self.addon.cache_file(self.repo)

    def test_git_unavailable(self, tool):
        args = ['scan', '--cache-dir', self.cache_dir, '--repo', self.repo.location]
        options, _ = tool.parse_args(args)
        assert options.cache['git']
        with patch('pkgcheck.git.find_binary') as find_binary:
            find_binary.side_effect = CommandNotFound('git not found')
            addon = git.GitAddon(options)
            assert not addon.options.cache['git']

    def test_no_gitignore(self):
        assert self.addon._gitignore is None
        assert not self.addon.gitignored('')

    def test_failed_gitignore(self):
        with open(pjoin(self.repo.location, '.gitignore'), 'w') as f:
            f.write('.*.swp\n')
        with patch('pkgcheck.git.open') as fake_open:
            fake_open.side_effect = IOError('file reading failure')
            assert self.addon._gitignore is None

    def test_gitignore(self):
        for path in ('.gitignore', '.git/info/exclude'):
            file_path = pjoin(self.repo.location, path)
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, 'w') as f:
                f.write('.*.swp\n')
            assert self.addon.gitignored('.foo.swp')
            assert self.addon.gitignored(pjoin(self.repo.location, '.foo.swp'))
            assert not self.addon.gitignored('foo.swp')
            assert not self.addon.gitignored(pjoin(self.repo.location, 'foo.swp'))

    def test_cache_disabled(self, tool):
        args = ['scan', '--cache', 'no', '--repo', self.repo.location]
        options, _ = tool.parse_args(args)
        addon = git.GitAddon(options)
        addon.update_cache()
        assert not os.path.exists(self.cache_file)

    def test_non_git_repo(self):
        self.addon.update_cache()
        assert not os.path.exists(self.cache_file)

    def test_git_repo_missing_origin_head(self, make_git_repo):
        """Repos missing the origin/HEAD ref are skipped."""
        make_git_repo(self.repo.location, commit=True)
        self.addon.update_cache()
        assert not os.path.exists(self.cache_file)

    def test_git_repo_no_pkg_commits(self, make_git_repo):
        """Cache file isn't updated if no relevant commits exist."""
        parent_repo = make_git_repo(commit=True)
        child_repo = make_git_repo(self.repo.location, commit=False)
        child_repo.run(['git', 'remote', 'add', 'origin', parent_repo.path])
        child_repo.run(['git', 'pull', 'origin', 'master'])
        child_repo.run(['git', 'remote', 'set-head', 'origin', 'master'])
        self.addon.update_cache()
        assert not os.path.exists(self.cache_file)

    def test_cache_creation_and_load(self, repo, make_git_repo):
        parent_repo = make_git_repo(repo.location, commit=True)
        # create a pkg and commit it
        repo.create_ebuild('cat/pkg-0')
        parent_repo.add_all('cat/pkg-0')

        child_repo = make_git_repo(self.repo.location, commit=False)
        child_repo.run(['git', 'remote', 'add', 'origin', parent_repo.path])
        child_repo.run(['git', 'pull', 'origin', 'master'])
        child_repo.run(['git', 'remote', 'set-head', 'origin', 'master'])
        self.addon.update_cache()
        assert atom_cls('=cat/pkg-0') in self.addon.cached_repo(git.GitAddedRepo)

        with patch('pkgcheck.caches.CachedAddon.save_cache') as save_cache:
            # verify the cache was loaded and not regenerated
            self.addon.update_cache()
            save_cache.assert_not_called()
            # and is regenerated on a forced cache update
            self.addon.update_cache(force=True)
            save_cache.assert_called_once()

        # create another pkg and commit it to the parent repo
        repo.create_ebuild('cat/pkg-1')
        parent_repo.add_all('cat/pkg-1')
        self.addon.update_cache()
        assert atom_cls('=cat/pkg-1') not in self.addon.cached_repo(git.GitAddedRepo)

        # new package is seen after child repo pulls changes
        child_repo.run(['git', 'pull', 'origin', 'master'])
        self.addon.update_cache()
        assert atom_cls('=cat/pkg-1') in self.addon.cached_repo(git.GitAddedRepo)

    def test_outdated_cache(self, repo, make_git_repo):
        parent_repo = make_git_repo(repo.location, commit=True)
        # create a pkg and commit it
        repo.create_ebuild('cat/pkg-0')
        parent_repo.add_all('cat/pkg-0')

        child_repo = make_git_repo(self.repo.location, commit=False)
        child_repo.run(['git', 'remote', 'add', 'origin', parent_repo.path])
        child_repo.run(['git', 'pull', 'origin', 'master'])
        child_repo.run(['git', 'remote', 'set-head', 'origin', 'master'])
        self.addon.update_cache()
        assert atom_cls('=cat/pkg-0') in self.addon.cached_repo(git.GitAddedRepo)

        # increment cache version and dump cache
        cache = self.addon.load_cache(self.cache_file)
        cache.version += 1
        self.addon.save_cache(cache, self.cache_file)

        # verify cache load causes regen
        with patch('pkgcheck.caches.CachedAddon.save_cache') as save_cache:
            self.addon.update_cache()
            save_cache.assert_called_once()

    def test_error_creating_cache(self, repo, make_git_repo):
        parent_repo = make_git_repo(repo.location, commit=True)
        # create a pkg and commit it
        repo.create_ebuild('cat/pkg-0')
        parent_repo.add_all('cat/pkg-0')

        child_repo = make_git_repo(self.repo.location, commit=False)
        child_repo.run(['git', 'remote', 'add', 'origin', parent_repo.path])
        child_repo.run(['git', 'pull', 'origin', 'master'])
        child_repo.run(['git', 'remote', 'set-head', 'origin', 'master'])

        with patch('pkgcheck.git.ParsedGitRepo.parse_git_log') as parse_git_log:
            parse_git_log.side_effect = git.GitError('git parsing failed')
            with pytest.raises(UserException, match='git parsing failed'):
                self.addon.update_cache()

    def test_error_loading_cache(self, repo, make_git_repo):
        parent_repo = make_git_repo(repo.location, commit=True)
        # create a pkg and commit it
        repo.create_ebuild('cat/pkg-0')
        parent_repo.add_all('cat/pkg-0')

        child_repo = make_git_repo(self.repo.location, commit=False)
        child_repo.run(['git', 'remote', 'add', 'origin', parent_repo.path])
        child_repo.run(['git', 'pull', 'origin', 'master'])
        child_repo.run(['git', 'remote', 'set-head', 'origin', 'master'])
        self.addon.update_cache()
        assert atom_cls('=cat/pkg-0') in self.addon.cached_repo(git.GitAddedRepo)

        with patch('pkgcheck.caches.pickle.load') as pickle_load:
            # catastrophic errors are raised
            pickle_load.side_effect = MemoryError('unpickling failed')
            with pytest.raises(MemoryError, match='unpickling failed'):
                self.addon.update_cache()

            # but various load failure exceptions cause cache regen
            pickle_load.side_effect = Exception('unpickling failed')
            with patch('pkgcheck.caches.CachedAddon.save_cache') as save_cache:
                self.addon.update_cache()
                save_cache.assert_called_once()

    def test_error_dumping_cache(self, repo, make_git_repo):
        parent_repo = make_git_repo(repo.location, commit=True)
        # create a pkg and commit it
        repo.create_ebuild('cat/pkg-0')
        parent_repo.add_all('cat/pkg-0')

        child_repo = make_git_repo(self.repo.location, commit=False)
        child_repo.run(['git', 'remote', 'add', 'origin', parent_repo.path])
        child_repo.run(['git', 'pull', 'origin', 'master'])
        child_repo.run(['git', 'remote', 'set-head', 'origin', 'master'])

        # verify IO related dump failures are raised
        with patch('pkgcheck.caches.pickle.dump') as pickle_dump:
            pickle_dump.side_effect = IOError('unpickling failed')
            with pytest.raises(UserException, match='failed dumping git cache'):
                self.addon.update_cache()

    def test_commits_repo(self, repo, make_repo, make_git_repo):
        parent_repo = repo
        parent_git_repo = make_git_repo(repo.location, commit=True)
        # create a pkg and commit it
        parent_repo.create_ebuild('cat/pkg-0')
        parent_git_repo.add_all('cat/pkg-0')

        child_git_repo = make_git_repo(self.repo.location, commit=False)
        child_git_repo.run(['git', 'remote', 'add', 'origin', parent_git_repo.path])
        child_git_repo.run(['git', 'pull', 'origin', 'master'])
        child_git_repo.run(['git', 'remote', 'set-head', 'origin', 'master'])
        self.addon.update_cache()

        # no new pkg commits exist locally in the child repo
        commits_repo = self.addon.commits_repo(git.GitChangedRepo)
        assert len(commits_repo) == 0

        # create a pkg in the child repo and commit it
        child_repo = make_repo(child_git_repo.path)
        child_repo.create_ebuild('cat/pkg-1')
        child_git_repo.add_all('cat/pkg-1')

        # pkg commits now exist locally in the child repo
        commits_repo = self.addon.commits_repo(git.GitChangedRepo)
        assert len(commits_repo) == 1
        assert atom_cls('=cat/pkg-1') in commits_repo

        # failing to parse git log yields an empty repo
        with patch('pkgcheck.git.ParsedGitRepo.parse_git_log') as parse_git_log:
            parse_git_log.side_effect = git.GitError('git parsing failed')
            commits_repo = self.addon.commits_repo(git.GitChangedRepo)
            assert len(commits_repo) == 0

        # disabled git cache support also yields an empty repo
        self.addon.options.cache['git'] = False
        commits_repo = self.addon.commits_repo(git.GitChangedRepo)
        assert len(commits_repo) == 0

    def test_commits(self, repo, make_repo, make_git_repo):
        parent_repo = repo
        parent_git_repo = make_git_repo(repo.location, commit=True)
        # create a pkg and commit it
        parent_repo.create_ebuild('cat/pkg-0')
        parent_git_repo.add_all('cat/pkg-0')

        child_git_repo = make_git_repo(self.repo.location, commit=False)
        child_git_repo.run(['git', 'remote', 'add', 'origin', parent_git_repo.path])
        child_git_repo.run(['git', 'pull', 'origin', 'master'])
        child_git_repo.run(['git', 'remote', 'set-head', 'origin', 'master'])
        self.addon.update_cache()

        # no new commits exist locally in the child repo
        assert len(list(self.addon.commits())) == 0

        # create a pkg in the child repo and commit it
        child_repo = make_repo(child_git_repo.path)
        child_repo.create_ebuild('cat/pkg-1')
        child_git_repo.add_all('cat/pkg-1')

        # commits now exist locally in the child repo
        commits = list(self.addon.commits())
        assert len(commits) == 1
        assert commits[0].message == ['cat/pkg-1']

        # failing to parse git log yields no commits
        with patch('pkgcheck.git.ParsedGitRepo.parse_git_log') as parse_git_log:
            parse_git_log.side_effect = git.GitError('git parsing failed')
            assert len(list(self.addon.commits())) == 0

        # disabled git cache support also yields no commits
        self.addon.options.cache['git'] = False
        assert len(list(self.addon.commits())) == 0
