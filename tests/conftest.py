import os
import tempfile
import textwrap
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import pytest
from pkgcheck.addons.git import GitConfig
from pkgcheck.cli import Tool
from pkgcheck.reporters import StrReporter
from pkgcheck.results import Result
from pkgcheck.scripts import pkgcheck
from pkgcore import const as pkgcore_const
from snakeoil.cli.arghparse import ArgumentParser
from snakeoil.contexts import os_environ
from snakeoil.formatters import PlainTextFormatter
from snakeoil.osutils import pjoin

pytest_plugins = ['pkgcore']
REPO_ROOT = Path(__file__).parent.parent


def pytest_configure():
    # export repo root for test modules to use
    pytest.REPO_ROOT = REPO_ROOT


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
    stack.enter_context(os_environ(**(git_config := GitConfig()).config_env))

    def unpatch():
        stack.close()
        git_config.close()

    request.addfinalizer(unpatch)


@pytest.fixture(scope="session")
def testconfig(tmp_path_factory):
    """Generate a portage config that sets the default repo to the bundled standalone repo.

    Also, repo entries for all the bundled test repos.
    """
    config = tmp_path_factory.mktemp('testconfig')
    repos_conf = config / 'repos.conf'
    stubrepo = pjoin(pkgcore_const.DATA_PATH, 'stubrepo')
    testdir = REPO_ROOT / 'testdata/repos'
    with open(repos_conf, 'w') as f:
        f.write(textwrap.dedent(f"""\
            [DEFAULT]
            main-repo = standalone
            [stubrepo]
            location = {stubrepo}
        """))
        for repo in testdir.iterdir():
            f.write(f'[{repo.name}]\n')
            f.write(f'location = {repo}\n')
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
    fakerepo = tmp_path_factory.mktemp('fakerepo')
    (profiles := fakerepo / 'profiles').mkdir(parents=True)
    (profiles / 'repo_name').write_text('fakerepo\n')
    (metadata := fakerepo / 'metadata').mkdir(parents=True)
    (metadata / 'layout.conf').write_text('masters =\n')
    return fakerepo


@pytest.fixture(scope="session")
def tool(testconfig):
    """Generate a tool utility for running pkgcheck."""
    tool = Tool(pkgcheck.argparser)
    tool.parser.set_defaults(config_path=testconfig)
    return tool


@pytest.fixture
def parser():
    """Return a copy of the main pkgcheck argparser."""
    return ArgumentParser(suppress=True, parents=(pkgcheck.argparser,))
