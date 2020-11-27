import os
import subprocess
import textwrap

import pytest
from pkgcheck.scripts import pkgcheck
from pkgcore import const as pkgcore_const
from pkgcore.ebuild import cpv as cpv_mod
from pkgcore.ebuild import repo_objs, repository
from pkgcore.util.commandline import Tool
from snakeoil import klass
from snakeoil.fileutils import touch
from snakeoil.osutils import pjoin


@pytest.fixture(scope="session")
def fakeconfig(tmp_path_factory):
    """Generate a portage config that sets the default repo to pkgcore's stubrepo."""
    fakeconfig = tmp_path_factory.mktemp('fakeconfig')
    repos_conf = fakeconfig / 'repos.conf'
    stubrepo = pjoin(pkgcore_const.DATA_PATH, 'stubrepo')
    with open(repos_conf, 'w') as f:
        f.write(textwrap.dedent(f"""\
            [DEFAULT]
            main-repo = stubrepo

            [stubrepo]
            location = {stubrepo}
        """))
    return str(fakeconfig)


@pytest.fixture(scope="session")
def testconfig(tmp_path_factory):
    """Generate a portage config that sets the default repo to pkgcore's stubrepo.

    Also, repo entries for all the bundled test repos.
    """
    testconfig = tmp_path_factory.mktemp('testconfig')
    repos_conf = testconfig / 'repos.conf'
    stubrepo = pjoin(pkgcore_const.DATA_PATH, 'stubrepo')
    testdir = pjoin(os.path.dirname(os.path.dirname(__file__)), 'repos')
    with open(repos_conf, 'w') as f:
        f.write(textwrap.dedent(f"""\
            [DEFAULT]
            main-repo = stubrepo

            [stubrepo]
            location = {stubrepo}
            [overlayed]
            location = {pjoin(testdir, 'overlayed')}
        """))
    return str(testconfig)


@pytest.fixture(scope="session")
def cache_dir(tmp_path_factory):
    """Generate a cache directory for pkgcheck."""
    cache_dir = tmp_path_factory.mktemp('cache')
    return str(cache_dir)


@pytest.fixture
def fakerepo(tmp_path):
    """Generate a stub repo."""
    fakerepo = str(tmp_path)
    os.makedirs(pjoin(fakerepo, 'profiles'))
    os.makedirs(pjoin(fakerepo, 'metadata'))
    with open(pjoin(fakerepo, 'profiles', 'repo_name'), 'w') as f:
        f.write('fakerepo\n')
    with open(pjoin(fakerepo, 'metadata', 'layout.conf'), 'w') as f:
        f.write('masters =\n')
    return fakerepo


@pytest.fixture(scope="session")
def tool(fakeconfig):
    """Generate a tool utility for running pkgcheck."""
    tool = Tool(pkgcheck.argparser)
    tool.parser.set_defaults(override_config=fakeconfig)
    return tool


class GitRepo:
    """Class for creating/manipulating git repos.

    Only relies on the git binary existing in order to limit
    dependency requirements.
    """

    def __init__(self, path, init=True, commit=False):
        self.path = path
        # initialize the repo
        if init:
            self._run(['git', 'init'])
            self._run(['git', 'config', 'user.email', 'person@email.com'])
            self._run(['git', 'config', 'user.name', 'Person'])
        if commit:
            if self.changes:
                # if files exist in the repo, add them in an initial commit
                self.add_all(msg='initial commit')
            else:
                # otherwise add a stub initial commit
                self.add(pjoin(self.path, '.init'), create=True)

    def _run(self, cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs):
        return subprocess.run(
            cmd, cwd=self.path, encoding='utf8', check=True,
            stdout=stdout, stderr=stderr, **kwargs)

    @property
    def changes(self):
        """Return a list of any untracked or modified files in the repo."""
        cmd = ['git', 'ls-files', '-mo', '--exclude-standard']
        p = self._run(cmd, stdout=subprocess.PIPE)
        return p.stdout.splitlines()

    @property
    def HEAD(self):
        """Return the commit hash for git HEAD."""
        p = self._run(['git', 'rev-parse', 'HEAD'], stdout=subprocess.PIPE)
        return p.stdout.strip()

    def __str__(self):
        return self.path

    def add(self, file_path, msg='commit', create=False):
        """Add a file and commit it to the repo."""
        if create:
            touch(pjoin(self.path, file_path))
        self._run(['git', 'add', file_path])
        self._run(['git', 'commit', '-m', msg])

    def add_all(self, msg='commit-all'):
        """Add and commit all tracked and untracked files."""
        self._run(['git', 'add', '--all'])
        self._run(['git', 'commit', '-m', msg])

    def remove(self, path, msg='remove'):
        """Remove a given file path and commit the change."""
        self._run(['git', 'rm', path])
        self._run(['git', 'commit', '-m', msg])

    def remove_all(self, path, msg='remove-all'):
        """Remove all files from a given path and commit the changes."""
        self._run(['git', 'rm', '-rf', path])
        self._run(['git', 'commit', '-m', msg])

    def move(self, path, new_path, msg='move'):
        """Move a given file path and commit the change."""
        self._run(['git', 'mv', path, new_path])
        self._run(['git', 'commit', '-m', msg])


@pytest.fixture
def git_repo(tmp_path):
    """Create an empty git repo with an initial commit."""
    return GitRepo(str(tmp_path), init=True, commit=True)


@pytest.fixture
def make_git_repo(tmp_path):
    """Factory for git repo creation."""
    def _make_git_repo(path=None, **kwargs):
        path = str(tmp_path) if path is None else path
        return GitRepo(path, **kwargs)
    return _make_git_repo


class EbuildRepo:
    """Class for creating/manipulating ebuild repos."""

    def __init__(self, path):
        self.path = path
        os.makedirs(pjoin(path, 'profiles'))
        os.makedirs(pjoin(path, 'metadata'))
        with open(pjoin(path, 'profiles', 'repo_name'), 'w') as f:
            f.write('fake\n')
        with open(pjoin(path, 'metadata', 'layout.conf'), 'w') as f:
            f.write('masters =\n')
        repo_config = repo_objs.RepoConfig(location=path)
        self._repo = repository.UnconfiguredTree(
            repo_config.location, repo_config=repo_config)

    def create_ebuild(self, cpvstr, data=''):
        cpv = cpv_mod.VersionedCPV(cpvstr)
        ebuild_dir = pjoin(self.path, cpv.category, cpv.package)
        os.makedirs(ebuild_dir, exist_ok=True)
        with open(pjoin(ebuild_dir, f'{cpv.package}-{cpv.version}.ebuild'), 'w') as f:
            f.write(data)

    __getattr__ = klass.GetAttrProxy('_repo')
    __dir__ = klass.DirProxy('_repo')


@pytest.fixture
def repo(tmp_path):
    """Create a generic ebuild repository."""
    return EbuildRepo(str(tmp_path))
