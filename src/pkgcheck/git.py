"""Git specific support and addon."""

import argparse
import os
import pickle
import shlex
import subprocess
from collections import namedtuple

from pkgcore.ebuild import cpv
from pkgcore.ebuild.atom import MalformedAtom
from pkgcore.ebuild.atom import atom as atom_cls
from pkgcore.repository import multiplex
from pkgcore.repository.util import SimpleTree
from pkgcore.test.misc import FakeRepo
from snakeoil.cli.exceptions import UserException
from snakeoil.demandload import demand_compile_regexp
from snakeoil.osutils import pjoin
from snakeoil.process import CommandNotFound, find_binary
from snakeoil.process.spawn import spawn_get_output
from snakeoil.strings import pluralism as _pl

from . import base
from .log import logger

# hacky ebuild path regexes for git log parsing, proper atom validation is handled later
_ebuild_path_regex_raw = '([^/]+)/([^/]+)/([^/]+)\\.ebuild'
_ebuild_path_regex = '(?P<category>[^/]+)/(?P<PN>[^/]+)/(?P<P>[^/]+)\\.ebuild'
demand_compile_regexp('ebuild_ADM_regex', fr'^(?P<status>[ADM])\t{_ebuild_path_regex}$')
demand_compile_regexp('ebuild_R_regex', fr'^(?P<status>R)\d+\t{_ebuild_path_regex_raw}\t{_ebuild_path_regex}$')

_GitCommit = namedtuple('GitCommit', [
    'commit', 'commit_date', 'author', 'committer', 'message'])
_GitPkgChange = namedtuple('GitPkgChange', [
    'atom', 'status', 'commit', 'commit_date', 'author', 'committer', 'message'])


class ParseGitRepo:
    """Parse repository git logs."""

    # git command to run on the targeted repo
    _git_cmd = 'git log --name-status --date=short'
    # selected file filter
    _diff_filter = None
    # filename for cache file, if None cache files aren't supported
    cache_name = None

    def __init__(self, repo, commit=None, **kwargs):
        self.location = repo.location
        self.cache_version = GitAddon.cache_version

        if commit is None:
            self.commit = 'origin/HEAD..master'
            self.pkg_map = self._pkg_changes(commit=self.commit, **kwargs)
        else:
            self.commit = commit
            self.pkg_map = self._pkg_changes(**kwargs)

    def update(self, commit, **kwargs):
        """Update an existing repo starting at a given commit hash."""
        self._pkg_changes(self.pkg_map, commit=self.commit, **kwargs)
        self.commit = commit

    @staticmethod
    def _parse_file_line(line):
        """Pull atoms and status from file change lines."""
        # match initially added ebuilds
        match = ebuild_ADM_regex.match(line)
        if match:
            status = match.group('status')
            category = match.group('category')
            pkg = match.group('P')
            try:
                return atom_cls(f'={category}/{pkg}'), status
            except MalformedAtom:
                return None

        # match renamed ebuilds
        match = ebuild_R_regex.match(line)
        if match:
            status = match.group('status')
            category = match.group('category')
            pkg = match.group('P')
            try:
                return atom_cls(f'={category}/{pkg}'), status
            except MalformedAtom:
                return None

    @classmethod
    def parse_git_log(cls, repo_path, git_cmd=None, commit=None,
                      pkgs=False, debug=False):
        """Parse git log output."""
        if git_cmd is None:
            git_cmd = cls._git_cmd
        cmd = shlex.split(git_cmd) if isinstance(git_cmd, str) else git_cmd
        # custom git log format, see the "PRETTY FORMATS" section of the git
        # log man page for details
        format_lines = [
            '# BEGIN COMMIT',
            '%h', # abbreviated commit hash
            '%cd', # commit date
            '%an <%ae>', # Author Name <author@email.com>
            '%cn <%ce>', # Committer Name <committer@email.com>
            '%B# END MESSAGE BODY', # commit message
        ]
        format_str = '%n'.join(format_lines)
        cmd.append(f'--pretty=tformat:{format_str}')

        if commit:
            if '..' in commit:
                cmd.append(commit)
            else:
                cmd.append(f'{commit}..origin/HEAD')
        else:
            cmd.append('origin/HEAD')

        git_log = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=repo_path)
        line = git_log.stdout.readline().decode().strip()
        if git_log.poll():
            error = git_log.stderr.read().decode().strip()
            logger.warning('skipping git checks: %s', error)
            return {}

        count = 1
        with base.ProgressManager(debug=debug) as progress:
            while line:
                commit = git_log.stdout.readline().decode().strip()
                commit_date = git_log.stdout.readline().decode().strip()
                author = git_log.stdout.readline().decode().strip()
                committer = git_log.stdout.readline().decode().strip()

                message = []
                while True:
                    line = git_log.stdout.readline().decode().strip('\n')
                    if line == '# END MESSAGE BODY':
                        break
                    message.append(line)

                # update progress output
                progress(f'{commit} commit #{count}, {commit_date}')
                count += 1

                if not pkgs:
                    yield _GitCommit(commit, commit_date, author, committer, message)

                # file changes
                while True:
                    line = git_log.stdout.readline().decode()
                    if line == '# BEGIN COMMIT\n' or not line:
                        break
                    if pkgs:
                        parsed = cls._parse_file_line(line.strip())
                        if parsed is not None:
                            atom, status = parsed
                            yield _GitPkgChange(
                                atom, status, commit, commit_date,
                                author, committer, message)

    def _pkg_changes(self, pkg_map=None, local=False, **kwargs):
        """Parse package changes from git log output."""
        if pkg_map is None:
            pkg_map = {}

        cmd = shlex.split(self._git_cmd)
        if self._diff_filter is not None:
            cmd.append(f'--diff-filter={self._diff_filter}')

        seen = set()
        for pkg in self.parse_git_log(self.location, cmd, pkgs=True, **kwargs):
            atom = pkg.atom
            if atom not in seen:
                seen.add(atom)
                data = {
                    'date': pkg.commit_date,
                    'status': pkg.status,
                    'commit': pkg.commit,
                }
                if local:
                    data.update({
                        'author': pkg.author,
                        'committer': pkg.committer,
                        'message': pkg.message,
                    })
                pkg_map.setdefault(atom.category, {}).setdefault(
                    atom.package, {})[atom.fullver] = data
        return pkg_map


class GitChangedRepo(ParseGitRepo):
    """Parse repository git log to determine locally changed packages."""

    _diff_filter = 'ARMD'


class GitModifiedRepo(ParseGitRepo):
    """Parse repository git log to determine latest ebuild modification dates."""

    cache_name = 'git-modified'
    _diff_filter = 'ARM'


class GitAddedRepo(ParseGitRepo):
    """Parse repository git log to determine ebuild added dates."""

    cache_name = 'git-added'
    _diff_filter = 'AR'


class GitRemovedRepo(ParseGitRepo):
    """Parse repository git log to determine ebuild removal dates."""

    cache_name = 'git-removed'
    _diff_filter = 'D'


class _UpstreamCommitPkg(cpv.VersionedCPV):
    """Fake packages encapsulating upstream commits parsed from git log."""

    def __init__(self, *args, date, status, commit):
        super().__init__(*args)

        # add additional attrs
        sf = object.__setattr__
        sf(self, 'date', date)
        sf(self, 'status', status)
        sf(self, 'commit', commit)


class _LocalCommitPkg(_UpstreamCommitPkg):
    """Fake packages encapsulating local commits parsed from git log."""

    def __init__(self, *args, author, committer, message, **kwargs):
        super().__init__(*args, **kwargs)

        # add additional attrs
        sf = object.__setattr__
        sf(self, 'author', author)
        sf(self, 'committer', committer)
        sf(self, 'message', message)


class _HistoricalRepo(SimpleTree):
    """Repository encapsulating historical data."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('pkg_klass', _UpstreamCommitPkg)
        super().__init__(*args, **kwargs)

    def _get_versions(self, cp_key):
        return tuple(self.cpv_dict[cp_key[0]][cp_key[1]].items())

    def _internal_gen_candidates(self, candidates, sorter, raw_pkg_cls, **kwargs):
        for cp in sorter(candidates):
            yield from sorter(
                raw_pkg_cls(cp[0], cp[1], ver, **data)
                for ver, data in self.versions.get(cp, ()))


class _ScanCommits(argparse.Action):
    """Argparse action that enables git commit checks."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, nargs=0, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):
        # avoid cyclic imports
        from . import const
        namespace.forced_checks.extend(
            name for name, cls in const.CHECKS.items() if cls.scope == base.commit_scope)
        setattr(namespace, self.dest, True)


class GitAddon(base.Addon):
    """Git repo support for various checks.

    Pkgcheck can create virtual package repos from a given git repo's history
    in order to provide more info for checks relating to stable requests,
    outdated blockers, or local commits. These virtual repos are cached and
    updated every run if new commits are detected.

    Git repos must have a supported config in order to work properly.
    Specifically, pkgcheck assumes that both origin and master branches exist
    and relate to the upstream and local development states, respectively.

    Additionally, the origin/HEAD ref must exist. If it doesn't, running ``git
    fetch origin`` should create it. Otherwise, using ``git remote set-head
    origin master`` or similar will also create the reference.
    """

    # used to check repo cache compatibility
    cache_version = 2

    @classmethod
    def mangle_argparser(cls, parser):
        group = parser.add_argument_group('git', docs=cls.__doc__)
        mutual_ex_group = group.add_mutually_exclusive_group()
        mutual_ex_group.add_argument(
            '--git-disable', action='store_true',
            help="disable git-related checks",
            docs="""
                Disable all checks that use git to parse repo logs.
            """)
        group.add_argument(
            '--git-cache', action='store_true',
            help="force git repo cache refresh",
            docs="""
                Parses a repo's git log and caches various historical information.
            """)
        mutual_ex_group.add_argument(
            '--commits', action=_ScanCommits, default=False,
            help="determine scan targets from local git repo commits",
            docs="""
                For a local git repo, pkgcheck will pull package targets to
                scan from the changes compared to the repo's origin.
            """)

    @classmethod
    def check_args(cls, parser, namespace):
        if namespace.commits:
            if namespace.targets:
                targets = ' '.join(namespace.targets)
                parser.error(
                    '--commits is mutually exclusive with '
                    f'target{_pl(namespace.targets)}: {targets}')
            try:
                repo = cls.commits_repo(cls, GitChangedRepo, options=namespace)
            except CommandNotFound:
                parser.error('git not available to determine targets for --commits')
            namespace.limiters = sorted(set(x.unversioned_atom for x in repo))

    def __init__(self, *args):
        super().__init__(*args)
        # disable git support if git isn't installed
        if not self.options.git_disable:
            try:
                find_binary('git')
            except CommandNotFound:
                self.options.git_disable = True

    @staticmethod
    def get_commit_hash(repo_location, commit='origin/HEAD'):
        """Retrieve a git repo's commit hash for a specific commit object."""
        if not os.path.exists(pjoin(repo_location, '.git')):
            raise ValueError
        ret, out = spawn_get_output(
            ['git', 'rev-parse', commit], cwd=repo_location)
        if ret != 0:
            raise ValueError(
                f'failed retrieving {commit} commit hash '
                f'for git repo: {repo_location}')
        return out[0].strip()

    def cached_repo(self, repo_cls, target_repo=None):
        cached_repo = None
        if target_repo is None:
            target_repo = self.options.target_repo

        if repo_cls.cache_name is None:
            raise TypeError(f"{repo_cls} doesn't support cached repos")

        if not self.options.git_disable:
            git_repos = []
            for repo in target_repo.trees:
                try:
                    commit = self.get_commit_hash(repo.location)
                except ValueError as e:
                    if str(e):
                        logger.warning('skipping git checks for %s repo: %s', repo, e)
                    continue

                # initialize cache file location
                cache_dir = pjoin(base.CACHE_DIR, 'repos', repo.repo_id.lstrip(os.sep))
                cache_file = pjoin(cache_dir, f'{repo_cls.cache_name}.pickle')

                git_repo = None
                cache_repo = True
                if not self.options.git_cache:
                    # try loading cached, historical repo data
                    try:
                        with open(cache_file, 'rb') as f:
                            git_repo = pickle.load(f)
                        if git_repo.cache_version != self.cache_version:
                            logger.debug('forcing git repo cache regen due to outdated version')
                            os.remove(cache_file)
                            git_repo = None
                    except FileNotFoundError as e:
                        pass
                    except (EOFError, AttributeError, TypeError) as e:
                        logger.debug('forcing git repo cache regen: %s', e)
                        os.remove(cache_file)
                        git_repo = None

                if (git_repo is not None and
                        repo.location == getattr(git_repo, 'location', None)):
                    if commit != git_repo.commit:
                        logger.debug(
                            'updating %s repo: %s -> %s',
                            repo_cls.cache_name, git_repo.commit[:10], commit[:10])
                        git_repo.update(commit, debug=self.options.debug)
                    else:
                        cache_repo = False
                else:
                    logger.debug(
                        'creating %s repo: %s', repo_cls.cache_name, commit[:10])
                    git_repo = repo_cls(repo, commit, debug=self.options.debug)

                # only enable repo queries if history was found, e.g. a
                # shallow clone with a depth of 1 won't have any history
                if git_repo.pkg_map:
                    git_repos.append(_HistoricalRepo(
                        git_repo.pkg_map, repo_id=f'{repo.repo_id}-history'))
                    # dump historical repo data
                    if cache_repo:
                        try:
                            os.makedirs(os.path.dirname(cache_file), exist_ok=True)
                            with open(cache_file, 'wb+') as f:
                                pickle.dump(git_repo, f)
                        except IOError as e:
                            msg = f'failed dumping git pkg repo: {cache_file!r}: {e.strerror}'
                            raise UserException(msg)
            else:
                if len(git_repos) > 1:
                    cached_repo = multiplex.tree(*git_repos)
                elif len(git_repos) == 1:
                    cached_repo = git_repos[0]

        return cached_repo

    def commits_repo(self, repo_cls, target_repo=None, options=None):
        options = options if options is not None else self.options
        if target_repo is None:
            target_repo = options.target_repo

        repo = FakeRepo()

        if not options.git_disable:
            try:
                origin = self.get_commit_hash(target_repo.location)
                master = self.get_commit_hash(target_repo.location, commit='master')
            except ValueError as e:
                if str(e):
                    logger.warning('skipping git commit checks: %s', e)
                return repo

            if origin != master:
                git_repo = repo_cls(target_repo, local=True)
                repo_id = f'{target_repo.repo_id}-commits'
                repo = _HistoricalRepo(
                    git_repo.pkg_map, pkg_klass=_LocalCommitPkg, repo_id=repo_id)

        return repo

    def commits(self, repo=None):
        path = repo.location if repo is not None else self.options.target_repo.location
        commits = iter(())

        if not self.options.git_disable:
            try:
                origin = self.get_commit_hash(path)
                master = self.get_commit_hash(path, commit='master')
            except ValueError as e:
                if str(e):
                    logger.warning('skipping git commit checks: %s', e)
                return commits

            if origin != master:
                commits = ParseGitRepo.parse_git_log(path, commit='origin/HEAD..master')

        return commits
