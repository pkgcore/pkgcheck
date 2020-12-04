import os
import subprocess
import tempfile
import textwrap
from contextlib import ExitStack
from unittest.mock import patch

import pytest
from pkgcheck.scripts import pkgcheck
from pkgcheck.reporters import StrReporter
from pkgcheck.results import Result
from pkgcore import const as pkgcore_const
from pkgcore.ebuild import cpv as cpv_mod
from pkgcore.ebuild import repo_objs, repository
from pkgcore.util.commandline import Tool
from snakeoil import klass
from snakeoil.formatters import PlainTextFormatter
from snakeoil.fileutils import touch
from snakeoil.osutils import pjoin


def pytest_assertrepr_compare(op, left, right):
    """Custom assertion failure output."""
    if isinstance(left, Result) and isinstance(right, Result) and op == "==":
        with tempfile.TemporaryFile() as f:
            with StrReporter(out=PlainTextFormatter(f)) as reporter:
                reporter.report(left)
                reporter.report(right)
                f.seek(0)
                left_val, right_val = f.read().decode().splitlines()
        return ["Result instances !=:", left_val, right_val]


@pytest.fixture(scope="session", autouse=True)
def default_session_fixture(request):
    """Fixture run globally for the entire test session."""
    stack = ExitStack()
    # don't load the default system or user config files
    stack.enter_context(patch('pkgcheck.cli.ConfigFileParser.default_configs', ()))

    def unpatch():
        stack.close()

    request.addfinalizer(unpatch)


@pytest.fixture(scope="session")
def stubconfig():
    """Generate a portage config that sets the default repo to pkgcore's stubrepo."""
    return pjoin(pkgcore_const.DATA_PATH, 'stubconfig')


@pytest.fixture(scope="session")
def testconfig(tmp_path_factory):
    """Generate a portage config that sets the default repo to the bundled standalone repo.

    Also, repo entries for all the bundled test repos.
    """
    config = tmp_path_factory.mktemp('testconfig')
    repos_conf = config / 'repos.conf'
    stubrepo = pjoin(pkgcore_const.DATA_PATH, 'stubrepo')
    testdir = pjoin(os.path.dirname(os.path.dirname(__file__)), 'repos')
    with open(repos_conf, 'w') as f:
        f.write(textwrap.dedent(f"""\
            [DEFAULT]
            main-repo = standalone
            [stubrepo]
            location = {stubrepo}
        """))
        for repo in os.listdir(testdir):
            f.write(f'[{repo}]\n')
            f.write(f'location = {pjoin(testdir, repo)}\n')
    profile_path = pjoin(stubrepo, 'profiles', 'default')
    os.symlink(profile_path, str(config / 'make.profile'))
    return str(config)


@pytest.fixture(scope="session")
def cache_dir(tmp_path_factory):
    """Generate a cache directory for pkgcheck."""
    cache_dir = tmp_path_factory.mktemp('cache')
    return str(cache_dir)


@pytest.fixture
def fakerepo(tmp_path_factory):
    """Generate a stub repo."""
    fakerepo = str(tmp_path_factory.mktemp('fakerepo'))
    os.makedirs(pjoin(fakerepo, 'profiles'))
    os.makedirs(pjoin(fakerepo, 'metadata'))
    with open(pjoin(fakerepo, 'profiles', 'repo_name'), 'w') as f:
        f.write('fakerepo\n')
    with open(pjoin(fakerepo, 'metadata', 'layout.conf'), 'w') as f:
        f.write('masters =\n')
    return fakerepo


@pytest.fixture(scope="session")
def tool(testconfig):
    """Generate a tool utility for running pkgcheck."""
    tool = Tool(pkgcheck.argparser)
    tool.parser.set_defaults(override_config=testconfig)
    return tool


@pytest.fixture
def parser():
    """Return a shallow copy of the main pkgcheck argparser."""
    return pkgcheck.argparser.copy()


class GitRepo:
    """Class for creating/manipulating git repos.

    Only relies on the git binary existing in order to limit
    dependency requirements.
    """

    def __init__(self, path, commit=False):
        self.path = path
        # initialize the repo
        self.run(['git', 'init'])
        self.run(['git', 'config', 'user.email', 'first.last@email.com'])
        self.run(['git', 'config', 'user.name', 'First Last'])
        if commit:
            if self.changes:
                # if files exist in the repo, add them in an initial commit
                self.add_all(msg='initial commit')
            else:
                # otherwise add a stub initial commit
                self.add(pjoin(self.path, '.init'), create=True)

    def run(self, cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs):
        return subprocess.run(
            cmd, cwd=self.path, encoding='utf8', check=True,
            stdout=stdout, stderr=stderr, **kwargs)

    @property
    def changes(self):
        """Return a list of any untracked or modified files in the repo."""
        cmd = ['git', 'ls-files', '-mo', '--exclude-standard']
        p = self.run(cmd, stdout=subprocess.PIPE)
        return p.stdout.splitlines()

    @property
    def HEAD(self):
        """Return the commit hash for git HEAD."""
        p = self.run(['git', 'rev-parse', '--short', 'HEAD'], stdout=subprocess.PIPE)
        return p.stdout.strip()

    def __str__(self):
        return self.path

    def commit(self, msg, signoff=False):
        """Make a commit to the repo."""
        if isinstance(msg, str):
            msg = msg.splitlines()
        if signoff:
            msg.extend(['', 'Signed-off-by: First Last <first.last@email.com>'])
        self.run(['git', 'commit', '-m', '\n'.join(msg)])

    def add(self, file_path, msg='commit', create=False, signoff=False):
        """Add a file and commit it to the repo."""
        if create:
            touch(pjoin(self.path, file_path))
        self.run(['git', 'add', file_path])
        self.commit(msg, signoff)

    def add_all(self, msg='commit-all', signoff=False):
        """Add and commit all tracked and untracked files."""
        self.run(['git', 'add', '--all'])
        self.commit(msg, signoff)

    def remove(self, path, msg='remove', signoff=False):
        """Remove a given file path and commit the change."""
        self.run(['git', 'rm', path])
        self.commit(msg, signoff)

    def remove_all(self, path, msg='remove-all', signoff=False):
        """Remove all files from a given path and commit the changes."""
        self.run(['git', 'rm', '-rf', path])
        self.commit(msg, signoff)

    def move(self, path, new_path, msg=None, signoff=False):
        """Move a given file path and commit the change."""
        msg = msg if msg is not None else f'{path} -> {new_path}'
        self.run(['git', 'mv', path, new_path])
        self.commit(msg, signoff)


@pytest.fixture
def git_repo(tmp_path_factory):
    """Create an empty git repo with an initial commit."""
    return GitRepo(str(tmp_path_factory.mktemp('git-repo')), commit=True)


@pytest.fixture
def make_git_repo(tmp_path_factory):
    """Factory for git repo creation."""
    def _make_git_repo(path=None, **kwargs):
        path = str(tmp_path_factory.mktemp('git-repo')) if path is None else path
        return GitRepo(path, **kwargs)
    return _make_git_repo


class EbuildRepo:
    """Class for creating/manipulating ebuild repos."""

    def __init__(self, path, repo_id='fake', masters=(), arches=()):
        self.path = path
        try:
            os.makedirs(pjoin(path, 'profiles'))
            with open(pjoin(path, 'profiles', 'repo_name'), 'w') as f:
                f.write(f'{repo_id}\n')
            os.makedirs(pjoin(path, 'metadata'))
            with open(pjoin(path, 'metadata', 'layout.conf'), 'w') as f:
                f.write(textwrap.dedent(f"""\
                    masters = {' '.join(masters)}
                    cache-formats =
                    thin-manifests = true
                """))
            if arches:
                with open(pjoin(path, 'profiles', 'arch.list'), 'w') as f:
                    f.write('\n'.join(arches) + '\n')
            os.makedirs(pjoin(path, 'eclass'))
        except FileExistsError:
            pass
        # forcibly create repo_config object, otherwise cached version might be used
        repo_config = repo_objs.RepoConfig(location=path, disable_inst_caching=True)
        self._repo = repository.UnconfiguredTree(path, repo_config=repo_config)

    def create_ebuild(self, cpvstr, data=None, **kwargs):
        cpv = cpv_mod.VersionedCPV(cpvstr)
        ebuild_dir = pjoin(self.path, cpv.category, cpv.package)
        os.makedirs(ebuild_dir, exist_ok=True)

        # use defaults for some ebuild metadata if unset
        eapi = kwargs.pop('eapi', '7')
        slot = kwargs.pop('slot', '0')
        desc = kwargs.pop('description', 'stub package description')
        homepage = kwargs.pop('homepage', 'https://github.com/pkgcore/pkgcheck')
        license = kwargs.pop('license', 'blank')

        with open(pjoin(ebuild_dir, f'{cpv.package}-{cpv.version}.ebuild'), 'w') as f:
            if self.repo_id == 'gentoo':
                f.write(textwrap.dedent("""\
                    # Copyright 1999-2020 Gentoo Authors
                    # Distributed under the terms of the GNU General Public License v2
                """))
            f.write(f'EAPI="{eapi}"\n')
            f.write(f'DESCRIPTION="{desc}"\n')
            f.write(f'HOMEPAGE="{homepage}"\n')
            f.write(f'SLOT="{slot}"\n')

            if license:
                f.write(f'LICENSE="{license}"\n')
                # create a fake license
                os.makedirs(pjoin(self.path, 'licenses'), exist_ok=True)
                touch(pjoin(self.path, 'licenses', license))

            for k, v in kwargs.items():
                # handle sequences such as KEYWORDS and IUSE
                if isinstance(v, (tuple, list)):
                    v = ' '.join(v)
                f.write(f'{k.upper()}="{v}"\n')
            if data:
                f.write(data.strip() + '\n')

    def __iter__(self):
        yield from iter(self._repo)

    __getattr__ = klass.GetAttrProxy('_repo')
    __dir__ = klass.DirProxy('_repo')


@pytest.fixture
def repo(tmp_path_factory):
    """Create a generic ebuild repository."""
    return EbuildRepo(str(tmp_path_factory.mktemp('repo')))


@pytest.fixture
def make_repo(tmp_path_factory):
    """Factory for ebuild repo creation."""
    def _make_repo(path=None, **kwargs):
        path = str(tmp_path_factory.mktemp('repo')) if path is None else path
        return EbuildRepo(path, **kwargs)
    return _make_repo
