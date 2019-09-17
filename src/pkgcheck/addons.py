"""Addon functionality shared by multiple checkers."""

import argparse
import os
import pickle
import shlex
import stat
import subprocess
from collections import UserDict, defaultdict, namedtuple
from functools import partial
from itertools import chain, filterfalse

from pkgcore.ebuild import cpv, domain, misc
from pkgcore.ebuild import profiles as profiles_mod
from pkgcore.ebuild import repo_objs
from pkgcore.ebuild.atom import MalformedAtom
from pkgcore.ebuild.atom import atom as atom_cls
from pkgcore.repository import multiplex
from pkgcore.repository.util import SimpleTree
from pkgcore.restrictions import packages, values
from pkgcore.test.misc import FakeRepo
from snakeoil import klass, mappings
from snakeoil.cli.arghparse import StoreBool
from snakeoil.cli.exceptions import UserException
from snakeoil.containers import ProtectedSet
from snakeoil.decorators import coroutine
from snakeoil.demandload import demand_compile_regexp
from snakeoil.log import suppress_logging
from snakeoil.osutils import abspath, pjoin
from snakeoil.process import CommandNotFound, find_binary
from snakeoil.process.spawn import spawn_get_output
from snakeoil.sequences import iflatten_instance
from snakeoil.strings import pluralism as _pl

from . import base
from .log import logger

# hacky ebuild path regexes for git log parsing, proper atom validation is handled later
_ebuild_path_regex_raw = '([^/]+)/([^/]+)/([^/]+)\\.ebuild'
_ebuild_path_regex = '(?P<category>[^/]+)/(?P<PN>[^/]+)/(?P<P>[^/]+)\\.ebuild'
demand_compile_regexp('ebuild_ADM_regex', fr'^(?P<status>[ADM])\t{_ebuild_path_regex}$')
demand_compile_regexp('ebuild_R_regex', fr'^(?P<status>R)\d+\t{_ebuild_path_regex_raw}\t{_ebuild_path_regex}$')


class ArchesAddon(base.Addon):

    @staticmethod
    def check_args(parser, namespace):
        arches = namespace.selected_arches
        target_repo = getattr(namespace, "target_repo", None)
        if target_repo is not None:
            all_arches = target_repo.known_arches
        else:
            all_arches = set()

        if arches is None:
            arches = (set(), all_arches)
        disabled, enabled = arches
        if not enabled:
            # enable all non-prefix arches
            enabled = set(arch for arch in all_arches if '-' not in arch)

        arches = set(enabled).difference(set(disabled))
        if all_arches:
            unknown_arches = arches.difference(all_arches)
            if unknown_arches:
                parser.error('unknown arch%s: %s (valid arches: %s)' % (
                    _pl(unknown_arches, plural='es'),
                    ', '.join(unknown_arches),
                    ', '.join(sorted(all_arches))))

        namespace.arches = tuple(sorted(arches))

    @classmethod
    def mangle_argparser(cls, parser):
        group = parser.add_argument_group('arches')
        group.add_argument(
            '-a', '--arches', dest='selected_arches', metavar='ARCH',
            action='csv_negations',
            help='comma separated list of arches to enable/disable',
            docs="""
                Comma separated list of arches to enable and disable.

                To specify disabled arches prefix them with '-'. Note that when
                starting the argument list with a disabled arch an equals sign
                must be used, e.g. -a=-arch, otherwise the disabled arch
                argument is treated as an option.

                By default all repo defined arches are used; however,
                stable-related checks (e.g. UnstableOnly) default to the set of
                arches having stable profiles in the target repo.
            """)


class QueryCacheAddon(base.Feed):

    priority = 1

    @staticmethod
    def mangle_argparser(parser):
        group = parser.add_argument_group('query caching')
        group.add_argument(
            '--reset-caching-per', dest='query_caching_freq',
            choices=('version', 'package', 'category'), default='package',
            help='control how often the cache is cleared '
                 '(version, package or category)')

    @staticmethod
    def check_args(parser, namespace):
        namespace.query_caching_freq = {
            'version': base.versioned_feed,
            'package': base.package_feed,
            'category': base.repository_feed,
            }[namespace.query_caching_freq]

    def __init__(self, options):
        super().__init__(options)
        self.query_cache = {}
        # XXX this should be logging debug info
        self.feed_type = self.options.query_caching_freq

    def feed(self, item):
        # XXX as should this.
        self.query_cache.clear()


_GitCommit = namedtuple('GitCommit', [
    'commit', 'commit_date', 'author', 'committer', 'message'])
_GitPkgChange = namedtuple('GitPkgChange', [
    'atom', 'status', 'commit', 'commit_date', 'author', 'committer', 'message'])


class ParseGitRepo:
    """Parse repository git logs."""

    # git command to run on the targeted repo
    _git_cmd = 'git log --name-status --date=short --reverse'
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

        for pkg in self.parse_git_log(self.location, cmd, pkgs=True, **kwargs):
            data = [pkg.atom.fullver, pkg.commit_date, pkg.status, pkg.commit]
            if local:
                data.extend([pkg.author, pkg.committer, pkg.message])
            pkg_map.setdefault(pkg.atom.category, {}).setdefault(
                pkg.atom.package, []).append(tuple(data))

        return pkg_map


class GitChangedRepo(ParseGitRepo):
    """Parse repository git log to determine locally changed packages."""

    _diff_filter = 'ARMD'


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

    def __init__(self, cat, pkg, data):
        ver, date, status, commit = data
        super().__init__(cat, pkg, ver)

        # add additional attrs
        sf = object.__setattr__
        sf(self, 'date', date)
        sf(self, 'status', status)
        sf(self, 'commit', commit)


class _LocalCommitPkg(_UpstreamCommitPkg):
    """Fake packages encapsulating local commits parsed from git log."""

    def __init__(self, cat, pkg, data):
        author, committer, message = data[-3:]
        super().__init__(cat, pkg, data[:-3])

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
    cache_version = 1

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


class ProfileData:

    def __init__(self, profile_name, key, provides, vfilter,
                 iuse_effective, use, pkg_use, masked_use, forced_use, lookup_cache, insoluble,
                 status, deprecated):
        self.key = key
        self.name = profile_name
        self.provides_repo = provides
        self.provides_has_match = getattr(provides, 'has_match', provides.match)
        self.iuse_effective = iuse_effective
        self.use = use
        self.pkg_use = pkg_use
        self.masked_use = masked_use
        self.forced_use = forced_use
        self.cache = lookup_cache
        self.insoluble = insoluble
        self.visible = vfilter.match
        self.status = status
        self.deprecated = deprecated

    def identify_use(self, pkg, known_flags):
        # note we're trying to be *really* careful about not creating
        # pointless intermediate sets unless required
        # kindly don't change that in any modifications, it adds up.
        enabled = known_flags.intersection(self.forced_use.pull_data(pkg))
        immutable = enabled.union(
            filter(known_flags.__contains__, self.masked_use.pull_data(pkg)))
        force_disabled = self.masked_use.pull_data(pkg)
        if force_disabled:
            enabled = enabled.difference(force_disabled)
        return immutable, enabled


class _ProfilesCache(UserDict):
    """Class used to encapsulate cached profile data."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cache_version = ProfileAddon.cache_version


class ProfileAddon(base.Addon):

    required_addons = (ArchesAddon,)

    # non-profile dirs found in the profiles directory, generally only in
    # the gentoo repo, but could be in overlays as well
    non_profile_dirs = frozenset(['desc', 'updates'])

    # used to check profile cache compatibility
    cache_version = 1

    @staticmethod
    def mangle_argparser(parser):
        group = parser.add_argument_group('profiles')
        group.add_argument(
            "--profiles-base", dest='profiles_dir', default=None,
            help="path to base profiles directory",
            docs="""
                The path to the base profiles directory. This will override the
                default usage of profiles bundled in the target repository;
                primarily for testing.
            """)
        group.add_argument(
            '--profile-cache', action=StoreBool,
            help="forcibly enable/disable profile cache usage",
            docs="""
                Significantly decreases profile load time by caching and reusing
                the resulting filters rather than rebuilding them for each run.

                Caches are used by default. In order to forcibly refresh them,
                enable this option. Conversely, if caches are unwanted disable
                this instead.
            """)
        group.add_argument(
            '-p', '--profiles', metavar='PROFILE', action='csv_negations',
            dest='profiles',
            help='comma separated list of profiles to enable/disable',
            docs="""
                Comma separated list of profiles to enable and disable for
                scanning. Any profiles specified in this fashion will be the
                only profiles that get scanned, skipping any disabled profiles.
                In addition, if no profiles are explicitly enabled, all
                profiles defined in the target repo's profiles.desc file will be
                scanned except those marked as experimental (exp).

                To specify disabled profiles prefix them with ``-`` which
                removes the from the list of profiles to be considered. Note
                that when starting the argument list with a disabled profile an
                equals sign must be used, e.g.  ``-p=-path/to/profile``,
                otherwise the disabled profile argument is treated as an
                option.

                The special keywords of ``stable``, ``dev``, ``exp``, and
                ``deprecated`` correspond to the lists of stable, development,
                experimental, and deprecated profiles, respectively. Therefore,
                to only scan all stable profiles pass the ``stable`` argument
                to --profiles. Additionally the keyword ``all`` can be used to
                scan all defined profiles in the target repo.
            """)

    @staticmethod
    def check_args(parser, namespace):
        profiles_dir = getattr(namespace, "profiles_dir", None)
        if profiles_dir is not None:
            profiles_dir = abspath(profiles_dir)
            if not os.path.isdir(profiles_dir):
                parser.error(f"invalid profiles base: {profiles_dir!r}")

        selected_profiles = namespace.profiles
        if selected_profiles is None:
            # disable exp profiles by default if no profiles are selected
            selected_profiles = (('exp',), ())

        if profiles_dir:
            profiles_obj = repo_objs.Profiles(
                namespace.target_repo.config, profiles_base=profiles_dir)
        else:
            profiles_obj = namespace.target_repo.profiles

        def norm_name(s):
            """Expand status keywords and format paths."""
            if s in ('dev', 'exp', 'stable', 'deprecated'):
                yield from profiles_obj.get_profiles(status=s)
            elif s == 'all':
                yield from profiles_obj
            else:
                yield profiles_obj[os.path.normpath(s)]

        disabled, enabled = selected_profiles
        disabled = set(disabled)
        enabled = set(enabled)

        # remove profiles that are both enabled and disabled
        toggled = enabled.intersection(disabled)
        enabled = enabled.difference(toggled)
        disabled = disabled.difference(toggled)
        ignore_deprecated = 'deprecated' not in enabled

        # Expand status keywords, e.g. 'stable' -> set of stable profiles, and
        # translate selections into profile objs.
        disabled = set(chain.from_iterable(map(norm_name, disabled)))
        enabled = set(chain.from_iterable(map(norm_name, enabled)))

        # If no profiles are enabled, then all that are defined in
        # profiles.desc are scanned except ones that are explicitly disabled.
        if not enabled:
            enabled = set(profiles_obj)

        profiles = enabled.difference(disabled)

        # disable profile cache usage for custom profiles directories
        if profiles_dir is not None:
            namespace.profile_cache = False
        namespace.forced_cache = bool(namespace.profile_cache)

        # We hold onto the profiles as we're going, due to the fact that
        # profile nodes are weakly cached; hold onto all for this loop, avoids
        # a lot of reparsing at the expense of slightly more memory usage
        # temporarily.
        cached_profiles = []

        arch_profiles = defaultdict(list)
        for p in profiles:
            if ignore_deprecated and p.deprecated:
                continue
            if p.arch is None:
                # if profile lacks arch setting, skip it
                continue

            try:
                profile = profiles_obj.create_profile(p)
            except profiles_mod.ProfileError as e:
                # Only throw errors if the profile was selected by the user, bad
                # repo profiles will be caught during repo metadata scans.
                if namespace.profiles is not None:
                    parser.error(f'invalid profile: {e.path!r}: {e.error}')
                continue

            cached_profiles.append(profile)
            arch_profiles[p.arch].append((profile, p))

        namespace.arch_profiles = arch_profiles

    @coroutine
    def _profile_files(self):
        """Given a profile object, return its file set and most recent mtime."""
        cache = {}
        while True:
            profile = (yield)
            profile_mtime = 0
            profile_files = []
            for node in profile.stack:
                mtime, files = cache.get(node.path, (0, []))
                if not mtime:
                    for f in os.listdir(node.path):
                        p = pjoin(node.path, f)
                        files.append(p)
                        st_obj = os.lstat(p)
                        if stat.S_ISREG(st_obj.st_mode) and st_obj.st_mtime > mtime:
                            mtime = st_obj.st_mtime
                    cache[node.path] = (mtime, files)
                if mtime > profile_mtime:
                    profile_mtime = mtime
                profile_files.extend(files)
            yield profile_mtime, frozenset(profile_files)

    @klass.jit_attr
    def profile_data(self):
        """Mapping of profile age and file sets used to check cache viability."""
        data = {}
        if self.options.profile_cache is None or self.options.profile_cache:
            gen_profile_data = self._profile_files()
            for profile_obj, profile in chain.from_iterable(
                    self.options.arch_profiles.values()):
                mtime, files = gen_profile_data.send(profile_obj)
                data[profile] = (mtime, files)
                next(gen_profile_data)
            del gen_profile_data
        return mappings.ImmutableDict(data)

    def __init__(self, options, arches=None):
        super().__init__(options)

        self.official_arches = options.target_repo.known_arches
        self.desired_arches = getattr(self.options, 'arches', None)
        if self.desired_arches is None or self.options.selected_arches is None:
            # copy it to be safe
            self.desired_arches = set(self.official_arches)

        self.global_insoluble = set()
        profile_filters = defaultdict(list)
        chunked_data_cache = {}
        cached_profiles = defaultdict(dict)

        if options.profile_cache or options.profile_cache is None:
            for repo in self.options.target_repo.trees:
                cache_dir = pjoin(base.CACHE_DIR, 'repos', repo.repo_id.lstrip(os.sep))
                cache_file = pjoin(cache_dir, 'profiles.pickle')
                # add profiles-base -> repo mapping to ease storage procedure
                cached_profiles[repo.config.profiles_base]['repo'] = repo
                # load cached profile filters by default
                if options.profile_cache is None:
                    try:
                        with open(cache_file, 'rb') as f:
                            cache = pickle.load(f)
                        if cache.cache_version == self.cache_version:
                            cached_profiles[repo.config.profiles_base].update(cache)
                        else:
                            logger.debug(
                                f'forcing %s profile cache regen '
                                'due to outdated version', repo.repo_id)
                            os.remove(cache_file)
                    except FileNotFoundError as e:
                        pass
                    except (EOFError, AttributeError, TypeError) as e:
                        logger.debug('forcing %s profile cache regen: %s', repo.repo_id, e)
                        os.remove(cache_file)

        for k in self.desired_arches:
            if k.lstrip("~") not in self.desired_arches:
                continue
            stable_key = k.lstrip("~")
            unstable_key = "~" + stable_key
            stable_r = packages.PackageRestriction(
                "keywords", values.ContainmentMatch2((stable_key,)))
            unstable_r = packages.PackageRestriction(
                "keywords", values.ContainmentMatch2((stable_key, unstable_key,)))

            default_masked_use = tuple(set(
                x for x in self.official_arches if x != stable_key))

            for profile_obj, profile in options.arch_profiles.get(k, []):
                files = self.profile_data.get(profile, None)
                try:
                    cached_profile = cached_profiles[profile.base][profile.path]
                    if files != cached_profile['files']:
                        # force refresh of outdated cache entry
                        raise KeyError

                    vfilter = cached_profile['vfilter']
                    immutable_flags = cached_profile['immutable_flags']
                    stable_immutable_flags = cached_profile['stable_immutable_flags']
                    enabled_flags = cached_profile['enabled_flags']
                    stable_enabled_flags = cached_profile['stable_enabled_flags']
                    pkg_use = cached_profile['pkg_use']
                    iuse_effective = cached_profile['iuse_effective']
                    use = cached_profile['use']
                    provides_repo = cached_profile['provides_repo']
                except KeyError:
                    logger.debug('profile regen: %s', profile.path)
                    with suppress_logging():
                        try:
                            vfilter = domain.generate_filter(profile_obj.masks, profile_obj.unmasks)

                            immutable_flags = profile_obj.masked_use.clone(unfreeze=True)
                            immutable_flags.add_bare_global((), default_masked_use)
                            immutable_flags.optimize(cache=chunked_data_cache)
                            immutable_flags.freeze()

                            stable_immutable_flags = profile_obj.stable_masked_use.clone(unfreeze=True)
                            stable_immutable_flags.add_bare_global((), default_masked_use)
                            stable_immutable_flags.optimize(cache=chunked_data_cache)
                            stable_immutable_flags.freeze()

                            enabled_flags = profile_obj.forced_use.clone(unfreeze=True)
                            enabled_flags.add_bare_global((), (stable_key,))
                            enabled_flags.optimize(cache=chunked_data_cache)
                            enabled_flags.freeze()

                            stable_enabled_flags = profile_obj.stable_forced_use.clone(unfreeze=True)
                            stable_enabled_flags.add_bare_global((), (stable_key,))
                            stable_enabled_flags.optimize(cache=chunked_data_cache)
                            stable_enabled_flags.freeze()

                            pkg_use = profile_obj.pkg_use
                            iuse_effective = profile_obj.iuse_effective
                            provides_repo = profile_obj.provides_repo

                            # finalize enabled USE flags
                            use = set()
                            misc.incremental_expansion(use, profile_obj.use, 'while expanding USE')
                            use = frozenset(use)
                        except profiles_mod.ProfileError:
                            # unsupported EAPI or other issue, profile checks will catch this
                            continue

                    if options.profile_cache or options.profile_cache is None:
                        cached_profiles[profile.base]['update'] = True
                        cached_profiles[profile.base][profile.path] = {
                            'files': files,
                            'vfilter': vfilter,
                            'immutable_flags': immutable_flags,
                            'stable_immutable_flags': stable_immutable_flags,
                            'enabled_flags': enabled_flags,
                            'stable_enabled_flags': stable_enabled_flags,
                            'pkg_use': pkg_use,
                            'iuse_effective': iuse_effective,
                            'use': use,
                            'provides_repo': provides_repo,
                        }

                # used to interlink stable/unstable lookups so that if
                # unstable says it's not visible, stable doesn't try
                # if stable says something is visible, unstable doesn't try.
                stable_cache = set()
                unstable_insoluble = ProtectedSet(self.global_insoluble)

                # few notes.  for filter, ensure keywords is last, on the
                # offchance a non-metadata based restrict foregos having to
                # access the metadata.
                # note that the cache/insoluble are inversly paired;
                # stable cache is usable for unstable, but not vice versa.
                # unstable insoluble is usable for stable, but not vice versa
                profile_filters[stable_key].append(ProfileData(
                    profile.path, stable_key,
                    provides_repo,
                    packages.AndRestriction(vfilter, stable_r),
                    iuse_effective,
                    use,
                    pkg_use,
                    stable_immutable_flags, stable_enabled_flags,
                    stable_cache,
                    ProtectedSet(unstable_insoluble),
                    profile.status,
                    profile.deprecated))

                profile_filters[unstable_key].append(ProfileData(
                    profile.path, unstable_key,
                    provides_repo,
                    packages.AndRestriction(vfilter, unstable_r),
                    iuse_effective,
                    use,
                    pkg_use,
                    immutable_flags, enabled_flags,
                    ProtectedSet(stable_cache),
                    unstable_insoluble,
                    profile.status,
                    profile.deprecated))

        # dump updated profile filters
        for k, v in cached_profiles.items():
            if v.pop('update', False):
                repo = v.pop('repo')
                cache_dir = pjoin(base.CACHE_DIR, 'repos', repo.repo_id.lstrip(os.sep))
                cache_file = pjoin(cache_dir, 'profiles.pickle')
                try:
                    os.makedirs(os.path.dirname(cache_file), exist_ok=True)
                    with open(cache_file, 'wb+') as f:
                        pickle.dump(_ProfilesCache(
                            cached_profiles[repo.config.profiles_base]), f)
                except IOError as e:
                    msg = (
                        f'failed dumping {repo.repo_id} profiles cache: '
                        f'{cache_file!r}: {e.strerror}')
                    if not options.forced_cache:
                        logger.warning(msg)
                    else:
                        raise UserException(msg)

        profile_evaluate_dict = {}
        for key, profile_list in profile_filters.items():
            similar = profile_evaluate_dict[key] = []
            for profile in profile_list:
                for existing in similar:
                    if (existing[0].masked_use == profile.masked_use and
                            existing[0].forced_use == profile.forced_use):
                        existing.append(profile)
                        break
                else:
                    similar.append([profile])

        self.profile_evaluate_dict = profile_evaluate_dict
        self.profile_filters = profile_filters

    def identify_profiles(self, pkg):
        # yields groups of profiles; the 'groups' are grouped by the ability to share
        # the use processing across each of 'em.
        l = []
        keywords = pkg.keywords
        unstable_keywords = tuple(f'~{x}' for x in keywords if x[0] != '~')
        for key in keywords + unstable_keywords:
            profile_grps = self.profile_evaluate_dict.get(key)
            if profile_grps is None:
                continue
            for profiles in profile_grps:
                l2 = [x for x in profiles if x.visible(pkg)]
                if not l2:
                    continue
                l.append(l2)
        return l

    def __getitem__(self, key):
        """Return profiles matching a given keyword."""
        return self.profile_filters[key]

    def get(self, key, default=None):
        """Return profiles matching a given keyword with a fallback if none exist."""
        try:
            return self.profile_filters[key]
        except KeyError:
            return default

    def __iter__(self):
        """Iterate over all profile data objects."""
        return chain.from_iterable(self.profile_filters.values())

    def __len__(self):
        return len([x for x in self])


class EvaluateDepSetAddon(base.Feed):

    required_addons = (ProfileAddon,)
    feed_type = base.versioned_feed
    priority = 1

    def __init__(self, options, profiles):
        super().__init__(options)
        self.pkg_evaluate_depsets_cache = {}
        self.pkg_profiles_cache = {}
        self.profiles = profiles

    def feed(self, item):
        self.pkg_evaluate_depsets_cache.clear()
        self.pkg_profiles_cache.clear()

    def collapse_evaluate_depset(self, pkg, attr, depset):
        depset_profiles = self.pkg_evaluate_depsets_cache.get((pkg, attr))
        if depset_profiles is None:
            depset_profiles = self.identify_common_depsets(pkg, depset)
            self.pkg_evaluate_depsets_cache[(pkg, attr)] = depset_profiles
        return depset_profiles

    def identify_common_depsets(self, pkg, depset):
        profile_grps = self.pkg_profiles_cache.get(pkg, None)
        if profile_grps is None:
            profile_grps = self.profiles.identify_profiles(pkg)
            self.pkg_profiles_cache[pkg] = profile_grps

        # strip use dep defaults so known flags get identified correctly
        diuse = frozenset([x[:-3] if x[-1] == ')' else x
                          for x in depset.known_conditionals])
        collapsed = {}
        for profiles in profile_grps:
            immutable, enabled = profiles[0].identify_use(pkg, diuse)
            collapsed.setdefault((immutable, enabled), []).extend(profiles)

        return [(depset.evaluate_depset(k[1], tristate_filter=k[0]), v)
                for k, v in collapsed.items()]


class StableArchesAddon(base.Addon):
    """Check relating to stable arches by default."""

    required_addons = (ArchesAddon,)

    def __init__(self, options, arches=None):
        super().__init__(options)
        # use known stable arches if arches aren't specified
        if options.selected_arches is None:
            stable_arches = set().union(*(repo.profiles.arches('stable')
                                   for repo in options.target_repo.trees))
        else:
            stable_arches = set(options.arches)

        options.stable_arches = stable_arches


class UnstatedIUSE(base.VersionedResult, base.Error):
    """Package is reliant on conditionals that aren't in IUSE."""

    def __init__(self, attr, flags, profile=None, num_profiles=None, **kwargs):
        super().__init__(**kwargs)
        self.attr = attr
        self.flags = tuple(flags)
        self.profile = profile
        self.num_profiles = num_profiles

    @property
    def desc(self):
        msg = [f'attr({self.attr})']
        if self.profile is not None:
            if self.num_profiles is not None:
                num_profiles = f' ({self.num_profiles} total)'
            else:
                num_profiles = ''
            msg.append(f'profile {self.profile!r}{num_profiles}')
        flags = ', '.join(self.flags)
        msg.extend([f'unstated flag{_pl(self.flags)}', f'[ {flags} ]'])
        return ': '.join(msg)


class UseAddon(base.Addon):

    required_addons = (ProfileAddon,)

    def __init__(self, options, profiles):
        super().__init__(options)

        # common profile elements
        c_implicit_iuse = set()
        if profiles:
            c_implicit_iuse = set.intersection(*(set(p.iuse_effective) for p in profiles))

        known_iuse = set()
        known_iuse_expand = set()

        for repo in options.target_repo.trees:
            known_iuse.update(flag for matcher, (flag, desc) in repo.config.use_desc)
            known_iuse_expand.update(
                flag for flags in repo.config.use_expand_desc.values()
                for flag, desc in flags)

        self.collapsed_iuse = misc.non_incremental_collapsed_restrict_to_data(
            ((packages.AlwaysTrue, known_iuse),),
            ((packages.AlwaysTrue, known_iuse_expand),),
        )
        self.profiles = profiles
        self.global_iuse = frozenset(known_iuse)
        self.global_iuse_expand = frozenset(known_iuse_expand)
        self.global_iuse_implicit = frozenset(c_implicit_iuse)
        self.ignore = not (c_implicit_iuse or known_iuse or known_iuse_expand)
        if self.ignore:
            logger.debug(
                'disabling use/iuse validity checks since no usable '
                'use.desc and use.local.desc were found')

    def allowed_iuse(self, pkg):
        # metadata_xml checks catch xml issues, suppress warning/error logs here
        with suppress_logging():
            return self.collapsed_iuse.pull_data(pkg).union(pkg.local_use)

    def get_filter(self, attr=None):
        if self.ignore:
            return self.fake_use_validate
        if attr is not None:
            return partial(self.use_validate, attr=attr)
        return self.use_validate

    @staticmethod
    def fake_use_validate(klasses, pkg, seq, attr=None):
        return {k: () for k in iflatten_instance(seq, klasses)}, ()

    def _flatten_restricts(self, nodes, skip_filter, stated, unstated, attr, restricts=None):
        for node in nodes:
            k = node
            v = restricts if restricts is not None else []
            if isinstance(node, packages.Conditional):
                # invert it; get only whats not in pkg.iuse
                unstated.update(filterfalse(stated.__contains__, node.restriction.vals))
                v.append(node.restriction)
                yield from self._flatten_restricts(
                    iflatten_instance(node.payload, skip_filter),
                    skip_filter, stated, unstated, attr, v)
                continue
            elif attr == 'required_use':
                unstated.update(filterfalse(stated.__contains__, node.vals))
            yield k, tuple(v)

    def _unstated_iuse(self, pkg, attr, unstated_iuse):
        """Determine if packages use unstated IUSE for a given attribute."""
        # determine profiles lacking USE flags
        if self.profiles:
            profiles_unstated = defaultdict(set)
            if attr is not None:
                for p in self.profiles:
                    profile_unstated = unstated_iuse - p.iuse_effective
                    if profile_unstated:
                        profiles_unstated[tuple(sorted(profile_unstated))].add(p.name)

            for unstated, profiles in profiles_unstated.items():
                profiles = sorted(profiles)
                if self.options.verbosity > 0:
                    for p in profiles:
                        yield UnstatedIUSE(attr, unstated, p, pkg=pkg)
                else:
                    num_profiles = len(profiles)
                    yield UnstatedIUSE(attr, unstated, profiles[0], num_profiles, pkg=pkg)
        elif unstated_iuse:
            # Remove global defined implicit USE flags, note that standalone
            # repos without profiles will currently lack any implicit IUSE.
            unstated_iuse -= self.global_iuse_implicit
            if unstated_iuse:
                yield UnstatedIUSE(attr, unstated_iuse, pkg=pkg)

    def use_validate(self, klasses, pkg, seq, attr=None):
        skip_filter = (packages.Conditional,) + klasses
        nodes = iflatten_instance(seq, skip_filter)
        unstated = set()
        vals = dict(self._flatten_restricts(
            nodes, skip_filter, stated=pkg.iuse_stripped, unstated=unstated, attr=attr))
        return vals, self._unstated_iuse(pkg, attr, unstated)
