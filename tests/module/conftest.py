import os
import subprocess
import textwrap

import pytest
from pkgcheck.scripts import pkgcheck
from pkgcore import const as pkgcore_const
from pkgcore.util.commandline import Tool
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
    """Class for creating/manipulating git repos."""

    def __init__(self, path, init=True):
        self.path = path
        if init:
            # initialize the repo
            subprocess.run(['git', 'init'], cwd=self.path)
            subprocess.run(['git', 'config', 'user.email', 'person@email.com'], cwd=self.path)
            subprocess.run(['git', 'config', 'user.name', 'Person'], cwd=self.path)
            # and add a stub initial commit
            self.admit(pjoin(self.path, '.init'), create=True)

    def __str__(self):
        return self.path

    def admit(self, path, create=False):
        """Add a file and commit it to the repo."""
        if create:
            touch(path)
        subprocess.run(['git', 'add', path], cwd=self.path)
        subprocess.run(['git', 'commit', '-m', path], cwd=self.path)


@pytest.fixture
def git_repo(tmp_path):
    """Create an empty git repo."""
    return GitRepo(str(tmp_path))
