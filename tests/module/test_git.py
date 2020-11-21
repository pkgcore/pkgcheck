import subprocess
from unittest.mock import patch

import pytest
from pkgcore.ebuild import atom
from pkgcore.restrictions import packages
from pkgcheck import base


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
