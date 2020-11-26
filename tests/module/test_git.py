import os
import subprocess
from unittest.mock import Mock, patch

import pytest
from pkgcore.ebuild import atom
from pkgcore.restrictions import packages
from pkgcheck import base
from pkgcheck.git import GitStash
from snakeoil.cli.exceptions import UserException
from snakeoil.fileutils import touch
from snakeoil.osutils import pjoin


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
            atom_restricts = [atom.atom('dev-libs/foo'), atom.atom('media-libs/bar')]
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
            atom_restricts = [atom.atom('dev-libs/foo'), atom.atom('media-libs/bar')]
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
        with pytest.raises(ValueError) as excinfo:
            with GitStash(tmp_path):
                pass
        assert 'not a git repo' in str(excinfo.value)

    def test_empty_git_repo(self, git_repo):
        with GitStash(git_repo.path):
            pass

    def test_untracked_file(self, git_repo):
        path = pjoin(git_repo.path, 'foo')
        touch(path)
        assert os.path.exists(path)
        with GitStash(git_repo.path):
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
            with pytest.raises(UserException) as excinfo:
                with GitStash(git_repo.path):
                    pass
            assert 'git failed stashing files' in str(excinfo.value)

    def test_failed_unstashing(self, git_repo):
        path = pjoin(git_repo.path, 'foo')
        touch(path)
        assert os.path.exists(path)
        with pytest.raises(UserException) as excinfo:
            with GitStash(git_repo.path):
                assert not os.path.exists(path)
                touch(path)
        assert 'git failed applying stash' in str(excinfo.value)
