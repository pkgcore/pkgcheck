"""Git specific support and addon."""

import argparse
import os
import re
import shlex
import subprocess
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from itertools import takewhile
import tempfile

from pathspec import PathSpec
from pkgcore.ebuild import cpv
from pkgcore.ebuild.atom import MalformedAtom
from pkgcore.ebuild.atom import atom as atom_cls
from pkgcore.repository import multiplex
from pkgcore.repository.util import SimpleTree
from pkgcore.restrictions import packages
from snakeoil.cli import arghparse
from snakeoil.contexts import GitStash
from snakeoil.klass import jit_attr
from snakeoil.mappings import ImmutableDict, OrderedSet
from snakeoil.osutils import pjoin
from snakeoil.process import CommandNotFound, find_binary
from snakeoil.strings import pluralism

from .. import base
from ..base import PkgcheckUserException
from ..checks import GitCommitsCheck
from ..log import logger
from . import caches


@dataclass(frozen=True, eq=False)
class GitCommit:
    """Git commit objects."""

    hash: str
    commit_time: int
    author: str
    committer: str
    message: tuple
    pkgs: ImmutableDict = ImmutableDict()

    def __str__(self):
        return self.hash

    def __hash__(self):
        return hash(self.hash)

    def __eq__(self, other):
        return self.hash == other.hash


@dataclass(frozen=True)
class GitPkgChange:
    """Git package change objects."""

    atom: atom_cls
    status: str
    commit: str
    commit_time: int
    old: atom_cls = None


class GitError(Exception):
    """Generic git-related error."""


class GitCache(caches.DictCache):
    """Dictionary-based cache that encapsulates git commit data."""

    def __init__(self, *args, commit):
        super().__init__(*args)
        self.commit = commit


class GitConfig:
    """Manages temporary file which holds git config for disabling
    safe directory feature of git."""

    def __init__(self):
        fd, self.path = tempfile.mkstemp()
        os.write(fd, b"[safe]\n\tdirectory = *\n")
        os.close(fd)

    @property
    def config_env(self):
        # ignore global user and system git config, but disable safe.directory
        return ImmutableDict(
            {
                "GIT_CONFIG_GLOBAL": self.path,
                "GIT_CONFIG_SYSTEM": "",
            }
        )

    def close(self):
        os.unlink(self.path)


class GitLog:
    """Iterator for decoded `git log` line output."""

    def __init__(self, cmd, path):
        self._running = False
        self.git_config = GitConfig()
        self.proc = subprocess.Popen(
            cmd,
            cwd=path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self.git_config.config_env,
        )

    def __iter__(self):
        return self

    def __next__(self):
        # use replacement character for non-UTF8 decoding issues (issue #166)
        line = self.proc.stdout.readline().decode("utf-8", "replace")

        # verify git log is running as expected after pulling the first line
        if not self._running:
            if self.proc.poll() or not line:
                error = self.proc.stderr.read().decode().strip()
                if "Invalid revision range" in error:
                    raise GitError(
                        f"failed running git log: {error}\nTry clearing the cache: pkgcheck cache -R"
                    )
                else:
                    raise GitError(f"failed running git log: {error}")
            self._running = True
            self.git_config.close()

        # EOF has been reached when readline() returns an empty string
        if not line:
            raise StopIteration

        return line.rstrip()


class _ParseGitRepo:
    """Generic iterator for custom git log output parsing support."""

    # git command to run on the targeted repo
    _git_cmd = "git log --name-status --diff-filter=ARMD -z"

    # custom git log format lines, see the "PRETTY FORMATS" section of
    # the git log man page for details
    _format = ()

    # path regexes for git log parsing, validation is handled on instantiation
    _ebuild_re = re.compile(r"^(?P<category>[^/]+)/[^/]+/(?P<package>[^/]+)\.ebuild$")

    def __init__(self, path, commit_range):
        self.path = os.path.realpath(path)
        cmd = shlex.split(self._git_cmd)
        cmd.append(f"--pretty=tformat:%n{'%n'.join(self._format)}")
        cmd.append(commit_range)
        cmd.extend(("--no-find-copies-harder", "--find-renames"))

        self.git_log = GitLog(cmd, self.path)
        # discard the initial newline
        next(self.git_log)

    def __iter__(self):
        return self

    def __next__(self):
        raise NotImplementedError(self.__next__)

    @property
    def changes(self):
        """Generator of file change status with changed packages."""
        changes = deque(next(self.git_log).strip("\x00").split("\x00"))
        while changes:
            status = changes.popleft()
            if status.startswith("R"):
                # matched R status change
                status = "R"
                old = changes.popleft()
                new = changes.popleft()
                if (mo := self._ebuild_re.match(old)) and (mn := self._ebuild_re.match(new)):
                    try:
                        old_pkg = atom_cls(f"={mo.group('category')}/{mo.group('package')}")
                        new_pkg = atom_cls(f"={mn.group('category')}/{mn.group('package')}")
                        yield status, [old_pkg, new_pkg]
                    except MalformedAtom:
                        continue
            else:
                # matched ADM status change
                path = changes.popleft()
                if mo := self._ebuild_re.match(path):
                    try:
                        pkg = atom_cls(f"={mo.group('category')}/{mo.group('package')}")
                        yield status, [pkg]
                    except MalformedAtom:
                        continue


class GitRepoCommits(_ParseGitRepo):
    """Parse git log output into an iterator of commit objects."""

    _format = (
        "%h",  # abbreviated commit hash
        "%ct",  # commit timestamp
        "%an <%ae>",  # Author Name <author@email.com>
        "%cn <%ce>",  # Committer Name <committer@email.com>
        "%B",  # commit message
    )

    def __next__(self):
        commit_hash = next(self.git_log)
        commit_time = int(next(self.git_log))
        author = next(self.git_log)
        committer = next(self.git_log)
        message = list(takewhile(lambda x: x != "\x00", self.git_log))
        pkgs = defaultdict(set)
        for status, atoms in self.changes:
            if status == "R":
                old, new = atoms
                pkgs["A"].add(new)
                pkgs["D"].add(old)
            else:
                pkgs[status].update(atoms)
        return GitCommit(commit_hash, commit_time, author, committer, message, ImmutableDict(pkgs))


class GitRepoPkgs(_ParseGitRepo):
    """Parse git log output into an iterator of package change objects."""

    _format = (
        "%h",  # abbreviated commit hash
        "%ct",  # commit time
    )

    def __init__(self, *args, local=False):
        super().__init__(*args)
        self.local = local
        self._pkgs = deque()

    def __next__(self):
        while True:
            try:
                return self._pkgs.popleft()
            except IndexError:
                commit_hash = next(self.git_log)
                commit_time = int(next(self.git_log).rstrip("\x00"))
                self._pkg_changes(commit_hash, commit_time)

    def _pkg_changes(self, commit_hash, commit_time):
        """Queue package change objects from git log file changes."""
        for status, pkgs in self.changes:
            if status == "R":
                old, new = pkgs
                if not self.local:  # treat rename as addition and removal
                    self._pkgs.append(GitPkgChange(new, "A", commit_hash, commit_time))
                    self._pkgs.append(GitPkgChange(old, "D", commit_hash, commit_time))
                else:
                    # renames are split into add/remove ops at
                    # the check level for the local commits repo
                    self._pkgs.append(GitPkgChange(new, "R", commit_hash, commit_time, old))
            else:
                self._pkgs.append(GitPkgChange(pkgs[0], status, commit_hash, commit_time))


class _GitCommitPkg(cpv.VersionedCPV):
    """Fake packages encapsulating commits parsed from git log."""

    __slots__ = ("commit", "old", "status", "time")

    # set multiple defaults for the fake package
    live = False
    slot = "0"

    def __init__(self, category, package, status, version, time, commit, old=None):
        super().__init__(category, package, version)

        # add additional attrs
        sf = object.__setattr__
        sf(self, "time", time)
        sf(self, "status", status)
        sf(self, "commit", commit)
        sf(self, "old", old)

    def old_pkg(self):
        """Create a new object from a rename commit's old atom."""
        return self.__class__(
            self.old.category,
            self.old.package,
            self.status,
            self.old.fullver,
            self.time,
            self.commit,
        )


class GitChangedRepo(SimpleTree):
    """Historical git repo consisting of the latest changed packages."""

    # selected pkg status filter
    _status_filter = {"A", "R", "M", "D"}

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("pkg_klass", _GitCommitPkg)
        super().__init__(*args, **kwargs)

    def _get_versions(self, cp):
        versions = []
        for status, data in self.cpv_dict[cp[0]][cp[1]].items():
            if status in self._status_filter:
                for commit in data:
                    versions.append((status, commit))
        return versions

    def _internal_gen_candidates(self, candidates, sorter, raw_pkg_cls, **kwargs):
        for cp in sorter(candidates):
            yield from sorter(
                raw_pkg_cls(cp[0], cp[1], status, *commit)
                for status, commit in self.versions.get(cp, ())
            )


class GitModifiedRepo(GitChangedRepo):
    """Historical git repo consisting of the latest modified packages."""

    _status_filter = {"A", "M"}


class GitAddedRepo(GitChangedRepo):
    """Historical git repo consisting of added packages."""

    _status_filter = {"A"}


class GitRemovedRepo(GitChangedRepo):
    """Historical git repo consisting of removed packages."""

    _status_filter = {"D"}


class _ScanGit(argparse.Action):
    """Argparse action that enables scanning against git commits or staged changes."""

    def __init__(self, *args, staged=False, **kwargs):
        super().__init__(*args, **kwargs)
        if staged:
            diff_cmd = ["git", "diff-index", "--name-only", "--cached", "-z"]
        else:
            diff_cmd = ["git", "diff-tree", "-r", "--name-only", "-z"]

        self.staged = staged
        self.diff_cmd = diff_cmd

    def default_ref(self, remote):
        return "HEAD" if self.staged else f"{remote}..HEAD"

    def _try_git_remote(self, parser, namespace):
        """Try to catch case of missing git remote HEAD ref."""
        try:
            subprocess.run(
                ["git", "rev-parse", namespace.git_remote],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=namespace.target_repo.location,
                check=True,
                encoding="utf8",
            )
        except FileNotFoundError as exc:
            parser.error(str(exc))
        except subprocess.CalledProcessError as exc:
            error = exc.stderr.splitlines()[0]
            if "ambiguous argument" in error and "unknown revision" in error:
                parser.error(
                    f"failed running git: {error}\nSuggested to configure the remote by running 'git remote set-head {namespace.git_remote} -a'"
                )

    def generate_restrictions(self, parser, namespace, ref):
        """Generate restrictions for a given diff command."""
        try:
            p = subprocess.run(
                self.diff_cmd + [ref],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=namespace.target_repo.location,
                check=True,
                encoding="utf8",
            )
        except FileNotFoundError as exc:
            parser.error(str(exc))
        except subprocess.CalledProcessError as exc:
            error = exc.stderr.splitlines()[0]
            if "ambiguous argument" in error and "unknown revision" in error:
                self._try_git_remote(parser, namespace)
            parser.error(f"failed running git: {error}")

        if not p.stdout:
            # no changes exist, exit early
            parser.exit()

        eclass_re = re.compile(r"^eclass/(?P<eclass>\S+)\.eclass$")
        eclasses, profiles, pkgs = OrderedSet(), OrderedSet(), OrderedSet()

        for path in p.stdout.strip("\x00").split("\x00"):
            path_components = path.split(os.sep)
            if mo := eclass_re.match(path):
                eclasses.add(mo.group("eclass"))
            elif path_components[0] == "profiles":
                profiles.add(path)
            elif path_components[0] in namespace.target_repo.categories:
                try:
                    pkgs.add(atom_cls(os.sep.join(path_components[:2])))
                except MalformedAtom:
                    continue

        restrictions = []
        if pkgs:
            restrict = packages.OrRestriction(*pkgs)
            restrictions.append((base.package_scope, restrict))
        if eclasses:
            restrictions.append((base.eclass_scope, eclasses))
        if profiles:
            restrictions.append((base.profile_node_scope, profiles))

        # no relevant targets, exit early
        if not restrictions:
            parser.exit()

        return restrictions

    def __call__(self, parser, namespace, value, option_string=None):
        if namespace.targets:
            targets = " ".join(namespace.targets)
            s = pluralism(namespace.targets)
            parser.error(f"{option_string} is mutually exclusive with target{s}: {targets}")

        if not self.staged:
            # avoid circular import issues
            from .. import objects

            # enable git checks
            namespace.enabled_checks.update(objects.CHECKS.select(GitCommitsCheck).values())

        # determine target ref
        ref = value if value is not None else self.default_ref(namespace.git_remote)
        setattr(namespace, self.dest, ref)

        # generate scanning restrictions
        namespace.restrictions = self.generate_restrictions(parser, namespace, ref)
        # ignore irrelevant changes during scan
        namespace.contexts.append(GitStash(namespace.target_repo.location, staged=self.staged))


class GitAddon(caches.CachedAddon):
    """Git repo support for various checks.

    Pkgcheck can create virtual package repos from a given git repo's history
    in order to provide more info for checks relating to stable requests,
    outdated blockers, or local commits. These virtual repos are cached and
    updated every run if new commits are detected.

    Git repos must have a supported config in order to work properly.
    Specifically, pkgcheck assumes that the origin branch exists and tracks
    upstream.

    Additionally, the origin/HEAD ref must exist. If it doesn't, running ``git
    remote set-head origin master`` or similar for other branches will create
    it.

    You can override the default git remote used for all git comparison using
    ``--git-remote``.
    """

    # cache registry
    cache = caches.CacheData(type="git", file="git.pickle", version=5)

    @classmethod
    def mangle_argparser(cls, parser):
        group: argparse.ArgumentParser = parser.add_argument_group("git", docs=cls.__doc__)
        git_opts = group.add_mutually_exclusive_group()
        git_opts.add_argument(
            "--commits",
            nargs="?",
            default=False,
            metavar="tree-ish",
            action=arghparse.Delayed,
            target=_ScanGit,
            priority=10,
            help="determine scan targets from unpushed commits",
            docs="""
                Targets are determined from the committed changes compared to a
                given reference that defaults to the repo's origin.

                For example, to scan all the packages that have been changed in
                the current branch compared to the branch named 'old' use
                ``pkgcheck scan --commits old``. For two separate branches
                named 'old' and 'new' use ``pkgcheck scan --commits old..new``.
            """,
        )
        git_opts.add_argument(
            "--staged",
            nargs="?",
            default=False,
            metavar="tree-ish",
            action=arghparse.Delayed,
            target=partial(_ScanGit, staged=True),
            priority=10,
            help="determine scan targets from staged changes",
            docs="""
                Targets are determined using all staged changes for the git
                repo. Unstaged changes and untracked files are ignored by
                temporarily stashing them during the scanning process.
            """,
        )
        group.add_argument(
            "--git-remote",
            default="origin",
            metavar="REMOTE",
            help="git remote used for all git comparison and operations",
            docs="""
                The git remote to be used for all operations by pkgcheck. The
                default value, and the recommended value is ``origin``, but
                you can use any valid git remote name.
            """,
        )

    def __init__(self, *args):
        super().__init__(*args)
        try:
            find_binary("git")
        except CommandNotFound:
            raise caches.CacheDisabled(self.cache)

        # mapping of repo locations to their corresponding git repo caches
        self._cached_repos = {}

    @jit_attr
    def _gitignore(self):
        """Load a repo's .gitignore and .git/info/exclude files for path matching."""
        patterns = []
        paths = (
            pjoin(self.options.target_repo.location, ".gitignore"),
            pjoin(self.options.target_repo.location, ".git/info/exclude"),
            pjoin(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "git/ignore"),
        )
        for path in paths:
            try:
                with open(path) as f:
                    patterns.extend(f)
            except (FileNotFoundError, IOError):
                pass
        if patterns:
            return PathSpec.from_lines("gitwildmatch", patterns)
        return None

    def gitignored(self, path):
        """Determine if a given path in a repository is matched by .gitignore settings."""
        if self._gitignore is not None:
            if path.startswith(self.options.target_repo.location):
                repo_prefix_len = len(self.options.target_repo.location) + 1
                path = path[repo_prefix_len:]
            return self._gitignore.match_file(path)
        return False

    @staticmethod
    def _get_commit_hash(path, commit):
        """Retrieve a git repo's commit hash for a specific commit object."""
        try:
            p = subprocess.run(
                ["git", "rev-parse", commit],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                cwd=path,
                check=True,
                encoding="utf8",
            )
        except subprocess.CalledProcessError:
            raise GitError(f"failed retrieving commit hash for git repo: {path!r}")
        return p.stdout.strip()

    @staticmethod
    def _get_current_branch(path, commit="HEAD"):
        """Retrieve a git repo's current branch for a specific commit object."""
        try:
            p = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", commit],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                cwd=path,
                check=True,
                encoding="utf8",
            )
        except subprocess.CalledProcessError:
            raise GitError(f"failed retrieving branch for git repo: {path!r}")
        return p.stdout.strip()

    @staticmethod
    def _get_default_branch(path, remote):
        """Retrieve a git repo's default branch used with origin remote."""
        try:
            p = subprocess.run(
                ["git", "symbolic-ref", f"refs/remotes/{remote}/HEAD"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                cwd=path,
                check=True,
                encoding="utf8",
            )
        except subprocess.CalledProcessError:
            raise GitError(f"failed retrieving branch for git repo: {path!r}")
        return p.stdout.strip().split("/")[-1]

    @staticmethod
    def pkg_history(repo, commit_range, data=None, local=False, verbosity=-1):
        """Create or update historical package data for a given commit range."""
        if data is None:
            data = {}
        seen = set()
        with base.ProgressManager(verbosity=verbosity) as progress:
            for pkg in GitRepoPkgs(repo.location, commit_range, local=local):
                atom = pkg.atom
                key = (atom, pkg.status)
                if key not in seen:
                    seen.add(key)
                    if local:
                        commit = (atom.fullver, pkg.commit_time, pkg.commit, pkg.old)
                    else:
                        date = datetime.fromtimestamp(pkg.commit_time).strftime("%Y-%m-%d")
                        progress(f"{repo} -- updating git cache: commit date: {date}")
                        commit = (atom.fullver, pkg.commit_time, pkg.commit)
                    data.setdefault(atom.category, {}).setdefault(atom.package, {}).setdefault(
                        pkg.status, []
                    ).append(commit)
        return data

    def update_cache(self, force=False):
        """Update related cache and push updates to disk."""
        remote = self.options.git_remote
        for repo in self.options.target_repo.trees:
            try:
                branch = self._get_current_branch(repo.location)
                default_branch = self._get_default_branch(repo.location, remote)
                # skip cache usage when not running on the default branch
                if branch != default_branch:
                    logger.debug(
                        "skipping %s git repo cache update on " "non-default branch %r",
                        repo,
                        branch,
                    )
                    continue
                commit = self._get_commit_hash(repo.location, f"{remote}/HEAD")
            except GitError:
                continue

            # initialize cache file location
            cache_file = self.cache_file(repo)
            git_cache = None
            cache_repo = True

            if not force:
                git_cache = self.load_cache(cache_file)

            if git_cache is None or commit != git_cache.commit:
                logger.debug("updating %s git repo cache to %s", repo, commit[:13])
                if git_cache is None:
                    data = {}
                    commit_range = f"{remote}/HEAD"
                else:
                    data = git_cache.data
                    commit_range = f"{git_cache.commit}..{remote}/HEAD"

                try:
                    self.pkg_history(
                        repo, commit_range, data=data, verbosity=self.options.verbosity
                    )
                except GitError as exc:
                    raise PkgcheckUserException(str(exc))
                git_cache = GitCache(data, self.cache, commit=commit)
            else:
                cache_repo = False

            if git_cache:
                self._cached_repos[repo.location] = git_cache
                # push repo to disk if it was created or updated
                if cache_repo:
                    self.save_cache(git_cache, cache_file)

    def cached_repo(self, repo_cls):
        git_repos = []
        for repo in self.options.target_repo.trees:
            git_cache = self._cached_repos.get(repo.location, {})
            git_repos.append(repo_cls(git_cache, repo_id=f"{repo.repo_id}-history"))

        if len(git_repos) > 1:
            return multiplex.tree(*git_repos)
        return git_repos[0]

    def commits_repo(self, repo_cls):
        target_repo = self.options.target_repo
        remote = self.options.git_remote
        data = {}

        try:
            origin = self._get_commit_hash(target_repo.location, f"{remote}/HEAD")
            head = self._get_commit_hash(target_repo.location, "HEAD")
            if origin != head:
                data = self.pkg_history(target_repo, f"{remote}/HEAD..HEAD", local=True)
        except GitError as exc:
            raise PkgcheckUserException(str(exc))

        repo_id = f"{target_repo.repo_id}-commits"
        return repo_cls(data, repo_id=repo_id)

    def commits(self):
        target_repo = self.options.target_repo
        remote = self.options.git_remote
        commits = ()

        try:
            origin = self._get_commit_hash(target_repo.location, f"{remote}/HEAD")
            head = self._get_commit_hash(target_repo.location, "HEAD")
            if origin != head:
                commits = GitRepoCommits(target_repo.location, f"{remote}/HEAD..HEAD")
        except GitError as exc:
            raise PkgcheckUserException(str(exc))

        return iter(commits)
