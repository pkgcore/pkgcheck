"""pkgcore-based QA utility for ebuild repos

pkgcheck is a QA utility based on **pkgcore**\\(5) that supports scanning
ebuild repositories for various issues.
"""

import argparse
import os
import textwrap
from collections import defaultdict
from contextlib import ExitStack
from functools import partial
from itertools import chain
from operator import attrgetter

from pkgcore import const as pkgcore_const
from pkgcore.repository import errors as repo_errors
from pkgcore.repository import multiplex
from pkgcore.restrictions import boolean, packages, values
from pkgcore.restrictions.util import collect_package_restrictions
from pkgcore.util import commandline, parserestrict
from snakeoil.cli import arghparse
from snakeoil.cli.exceptions import UserException
from snakeoil.formatters import decorate_forced_wrapping
from snakeoil.osutils import abspath, pjoin

from .. import argparsers, base, const, objects, reporters
from ..addons import init_addon
from ..caches import CachedAddon
from ..cli import ConfigFileParser
from ..eclass import matching_eclass
from ..pipeline import Pipeline

argparser = commandline.ArgumentParser(
    description=__doc__, script=(__file__, __name__))
subparsers = argparser.add_subparsers(description="check applets")

reporter_argparser = commandline.ArgumentParser(suppress=True)
reporter_options = reporter_argparser.add_argument_group('reporter options')
reporter_options.add_argument(
    '-R', '--reporter', action='store', default=None,
    help='use a non-default reporter',
    docs="""
        Select a reporter to use for output.

        Use ``pkgcheck show --reporters`` to see available options.
    """)
reporter_options.add_argument(
    '--format', dest='format_str', action='store', default=None,
    help='format string used with FormatReporter',
    docs="""
        Custom format string used to format output by FormatReporter.

        Supports python format string syntax where result object attribute names
        surrounded by curly braces are replaced with their values (if they exist).

        For example, ``--format '{category}/{package}/{package}-{version}.ebuild``
        will output ebuild paths in the target repo for results relating to
        specific ebuild versions. If a result is for the generic package (or a
        higher scope), no output will be produced for that result.

        Furthermore, no output will be produced if a result object is missing any
        requested attribute expansion in the format string. In other words,
        ``--format {foo}`` will never produce any output because no result has the
        ``foo`` attribute.
    """)


@reporter_argparser.bind_final_check
def _setup_reporter(parser, namespace):
    if namespace.reporter is None:
        namespace.reporter = sorted(
            objects.REPORTERS.values(), key=attrgetter('priority'), reverse=True)[0]
    else:
        try:
            namespace.reporter = objects.REPORTERS[namespace.reporter]
        except KeyError:
            available = ', '.join(objects.REPORTERS)
            parser.error(
                f"no reporter matches {namespace.reporter!r} "
                f"(available: {available})")

    if namespace.reporter is reporters.FormatReporter:
        if not namespace.format_str:
            parser.error('missing or empty --format option required by FormatReporter')
        namespace.reporter = partial(namespace.reporter, namespace.format_str)
    elif namespace.format_str is not None:
        parser.error('--format option is only valid when using FormatReporter')


config_argparser = commandline.ArgumentParser(suppress=True)
config_options = config_argparser.add_argument_group('config options')
config_options.add_argument(
    '--config', action=argparsers.ConfigArg, dest='config_file',
    help='use custom pkgcheck scan settings file',
    docs="""
        Load custom pkgcheck scan settings from a given file.

        Note that custom user settings override all other system and repo-level
        settings.

        It's also possible to disable all types of settings loading by
        specifying an argument of 'false' or 'no'.
    """)

scan = subparsers.add_parser(
    'scan', parents=(config_argparser, reporter_argparser,),
    description='scan targets for QA issues')
scan.add_argument(
    'targets', metavar='TARGET', nargs='*', action=arghparse.ParseNonblockingStdin,
    help='optional targets')

main_options = scan.add_argument_group('main options')
main_options.add_argument(
    '-r', '--repo', metavar='REPO', dest='target_repo',
    action=commandline.StoreRepoObject, repo_type='ebuild-raw', allow_external_repos=True,
    help='repo to pull packages from')
main_options.add_argument(
    '-f', '--filter', choices=('latest', 'repo'),
    help='limit targeted packages for scanning',
    docs="""
        Support limiting targeted packages for scanning using a chosen filter.

        If the 'repo' argument is used, all package visibility mechanisms used
        by the package manager when resolving package dependencies such as
        ACCEPT_KEYWORDS, ACCEPT_LICENSE, and package.mask will be enabled.

        If the 'latest' argument is used, only the latest package per slot of
        both VCS and non-VCS types will be scanned.
    """)
main_options.add_argument(
    '-j', '--jobs', type=arghparse.positive_int, default=os.cpu_count(),
    help='number of checks to run in parallel',
    docs="""
        Number of checks to run in parallel, defaults to using all available
        processors.
    """)
main_options.add_argument(
    '-t', '--tasks', type=arghparse.positive_int, default=os.cpu_count() * 5,
    help='number of asynchronous tasks to run concurrently',
    docs="""
        Number of asynchronous tasks to run concurrently (defaults to 5 * CPU count).
    """)
main_options.add_argument(
    '--cache', action=argparsers.CacheNegations,
    help='forcibly enable/disable caches',
    docs="""
        All cache types are enabled by default, this option explicitly sets
        which caches will be generated and used during scanning.

        To enable only certain cache types, specify them in a comma-separated
        list, e.g. ``--cache git,profiles`` will enable both the git and
        profiles caches.

        To disable specific cache types prefix them with ``-``. Note
        that when starting the argument list with a disabled value an equals
        sign must be used, e.g. ``--cache=-git``, otherwise the disabled
        argument is treated as an option.

        In order to disable all cache usage, it's easiest to use ``--cache no``
        instead of explicitly listing all disabled cache types.

        When disabled, no caches will be saved to disk and results requiring
        caches (e.g. git-related checks) will be skipped.
    """)
main_options.add_argument(
    '--cache-dir', type=arghparse.create_dir, default=const.USER_CACHE_DIR,
    help='directory to use for storing cache files')
main_options.add_argument(
    '--exit', metavar='KEYWORD', dest='exit_keywords',
    action=argparsers.ExitArgs, nargs='?', default=(),
    help='keywords that trigger an error exit status (comma-separated list)',
    docs="""
        Comma separated list of keywords to enable and disable that
        trigger a failed exit status. If no arguments or only disabled
        arguments are passed, the set of error level results are used
        as enabled arguments.

        To specify disabled keywords prefix them with ``-``. Also, the special
        arguments of ``error``, ``warning``, and ``info`` correspond to all
        error, warning, and info keywords, respectively.
    """)


check_options = scan.add_argument_group('check selection')
check_options.add_argument(
    '--net', nargs=0,
    action=arghparse.Delayed, target=argparsers.EnableNet, priority=-1,
    help='enable checks that require network access')
check_options.add_argument(
    '-s', '--scopes', metavar='SCOPE', dest='selected_scopes', default=(),
    action=arghparse.Delayed, target=argparsers.ScopeArgs, priority=1,
    help='limit checks to run by scope (comma-separated list)',
    docs="""
        Comma separated list of scopes to enable and disable for scanning. Any
        scopes specified in this fashion will affect the checks that get
        run. For example, running pkgcheck with only the repo scope
        enabled will cause only repo-level checks to run.

        Available scopes: %s
    """ % (', '.join(base.scopes)))
check_options.add_argument(
    '-c', '--checks', metavar='CHECK', dest='selected_checks', default=(),
    action=arghparse.Delayed, target=argparsers.CheckArgs, priority=2,
    help='limit checks to run (comma-separated list)',
    docs="""
        Comma separated list of checks to enable and disable for
        scanning. Any checks specified in this fashion will be the
        only checks that get run, skipping any disabled checks.

        To specify disabled checks prefix them with ``-``. Note that when
        starting the argument list with a disabled check an equals sign must
        be used, e.g. ``-c=-check``, otherwise the disabled check argument is
        treated as an option.

        The special argument of ``all`` corresponds to the list of all checks.
        Therefore, to forcibly enable all checks use ``-c all``.

        In addition, all network-related checks (which are disabled by default)
        can be enabled using ``-c net``. This allows for easily running only
        network checks without having to explicitly list them.

        Use ``pkgcheck show --checks`` see available options.
    """)
check_options.add_argument(
    '-k', '--keywords', metavar='KEYWORD', dest='selected_keywords', default=(),
    action=arghparse.Delayed, target=argparsers.KeywordArgs, priority=3,
    help='limit keywords to scan for (comma-separated list)',
    docs="""
        Comma separated list of keywords to enable and disable for
        scanning. Any keywords specified in this fashion will be the
        only keywords that get reported, skipping any disabled keywords.

        To specify disabled keywords prefix them with ``-``. Note that when
        starting the argument list with a disabled keyword an equals sign must
        be used, e.g. ``-k=-keyword``, otherwise the disabled keyword argument is
        treated as an option.

        The special arguments of ``error``, ``warning``, and ``info``
        correspond to the lists of error, warning, and info keywords,
        respectively. For example, to only scan for errors use ``-k error``.

        Use ``pkgcheck show --keywords`` to see available options.
    """)

scan.plugin = scan.add_argument_group('plugin options')


def _determine_target_repo(namespace):
    """Determine a target repo when none was explicitly selected.

    Returns a repository object if a matching one is found, otherwise None.
    """
    target_dir = namespace.cwd

    # pull a target directory from target args if they're path-based
    if namespace.targets and isinstance(namespace.targets, list):
        initial_target = namespace.targets[0]
        if os.path.exists(initial_target):
            # if initial target is an existing path, use it instead of cwd
            target = os.path.abspath(initial_target)
            if os.path.isfile(target):
                target = os.path.dirname(target)
            target_dir = target
        else:
            # initial target doesn't exist as a path, perhaps a repo ID?
            for repo in namespace.domain.ebuild_repos_raw:
                if initial_target == repo.repo_id:
                    # set scanning restriction so targets aren't parsed again
                    namespace.restrictions = [(base.repo_scope, packages.AlwaysTrue)]
                    return repo

    # determine target repo from the target directory
    for repo in namespace.domain.ebuild_repos_raw:
        if target_dir in repo:
            return repo

    # determine if CWD is inside an unconfigured repo
    try:
        repo = namespace.domain.find_repo(
            target_dir, config=namespace.config, configure=False)
    except (repo_errors.InitializationError, IOError) as e:
        raise argparse.ArgumentError(None, str(e))

    # fallback to the default repo
    if repo is None:
        repo = namespace.config.get_default('repo')
        # if the bundled stub repo is the default, no default repo exists
        if repo is None or repo.location == pjoin(pkgcore_const.DATA_PATH, 'stubrepo'):
            raise argparse.ArgumentError(None, 'no default repo found')

    return repo


def _path_restrict(path, repo):
    """Generate custom package restriction from a given path.

    This drops the repo restriction (initial entry in path restrictions)
    since runs can only be made against single repo targets so the extra
    restriction is redundant and breaks several custom sources involving
    raw pkgs (lacking a repo attr) or faked repos.
    """
    restrictions = []
    path = os.path.realpath(path)

    restrictions = repo.path_restrict(path)[1:]
    restrict = packages.AndRestriction(*restrictions) if restrictions else packages.AlwaysTrue

    # allow location specific scopes to override the path restrict scope
    for scope in (x for x in base.scopes.values() if x.level == 0):
        scope_path = os.path.realpath(pjoin(repo.location, scope.desc))
        if path.startswith(scope_path):
            break
    else:
        scope = _restrict_to_scope(restrict)

    return scope, restrict


def _restrict_to_scope(restrict):
    """Determine a given restriction's scope level."""
    for scope, attrs in (
            (base.version_scope, ['fullver', 'version', 'rev']),
            (base.package_scope, ['package']),
            (base.category_scope, ['category'])):
        if any(collect_package_restrictions(restrict, attrs)):
            return scope
    return base.repo_scope


@scan.bind_reset_defaults
def _setup_scan_defaults(parser, namespace):
    """Re-initialize default namespace settings per arg parsing run."""
    namespace.contexts = []
    namespace.restrictions = []
    namespace.filtered_keywords = None
    # all non-optional checks are run by default
    namespace.enabled_checks = set(objects.CHECKS.default.values())


@scan.bind_pre_parse
def _setup_scan_addons(parser, namespace):
    """Load all checks and their argparser changes before parsing."""
    for addon in base.get_addons(objects.CHECKS.values()):
        addon.mangle_argparser(parser)


@scan.bind_early_parse
def _setup_scan(parser, namespace, args):
    # parse --config option from command line args
    namespace, args = config_argparser.parse_known_args(args, namespace)

    # parser supporting config file options
    config_parser = ConfigFileParser(parser)

    # load default args from system/user configs if config-loading is allowed
    if namespace.config_file is None:
        configs = ConfigFileParser.default_configs
        namespace = config_parser.parse_config_options(namespace, configs=configs)

    # re-parse command line args to override config defaults
    namespace, _ = parser._parse_known_args(args, namespace)

    # Get the current working directory for repo detection and restriction
    # creation, fallback to the root dir if it's be removed out from under us.
    try:
        namespace.cwd = abspath(os.getcwd())
    except FileNotFoundError:
        namespace.cwd = '/'

    # if we have no target repo figure out what to use
    if namespace.target_repo is None:
        namespace.target_repo = _determine_target_repo(namespace)

    # determine if we're running in the gentoo repo or a clone
    namespace.gentoo_repo = 'gentoo' in namespace.target_repo.aliases

    # multiplex of target repo and its masters used for package existence queries
    namespace.search_repo = multiplex.tree(*namespace.target_repo.trees)

    # support loading repo-specific config settings from metadata/pkgcheck.conf
    repo_config_file = os.path.join(namespace.target_repo.location, 'metadata', 'pkgcheck.conf')

    configs = ()
    if os.path.isfile(repo_config_file):
        # repo settings take precedence over system/user settings
        configs += (repo_config_file,)
    if namespace.config_file is not None:
        # and custom user settings take precedence over everything
        if not namespace.config_file:
            configs = ()
        else:
            configs += (namespace.config_file,)

    if configs:
        namespace = config_parser.parse_config_options(namespace, configs=configs)

    # load repo-specific args from config if they exist, command line args override these
    for section in namespace.target_repo.aliases:
        if section in config_parser.config:
            namespace = config_parser.parse_config_options(namespace, section)
            break

    return namespace, args


def generate_restricts(repo, targets):
    """Generate scanning restrictions from given targets."""
    eclasses = set()
    for target in targets:
        # assume package restriction by default
        try:
            restrict = parserestrict.parse_match(target)
            scope = _restrict_to_scope(restrict)
            yield scope, restrict
        except parserestrict.ParseError as exc:
            # fallback to trying to create a path restrict
            path = os.path.realpath(target)
            try:
                yield _path_restrict(path, repo)
                continue
            except ValueError as e:
                # support direct eclass path targets
                if target.endswith('.eclass') and path in repo:
                    eclasses.add(os.path.basename(target)[:-7])
                    continue
                if os.path.exists(path) or os.path.isabs(target):
                    raise UserException(str(e))
            raise UserException(str(exc))

    # support eclass target restrictions
    if eclasses:
        func = partial(matching_eclass, frozenset(eclasses))
        restrict = values.AnyMatch(values.FunctionRestriction(func))
        yield base.eclass_scope, restrict


@scan.bind_final_check
def _validate_scan_args(parser, namespace):
    # use filtered repo if requested
    if namespace.filter == 'repo':
        namespace.target_repo = namespace.domain.ebuild_repos[namespace.target_repo.repo_id]

    restrictions = namespace.restrictions
    if not restrictions:
        if namespace.targets:
            # Collapse restrictions for passed in targets while keeping the
            # generator intact for piped in targets.
            restrictions = generate_restricts(namespace.target_repo, namespace.targets)
            if isinstance(namespace.targets, list):
                restrictions = list(restrictions)

                # collapse restrictions in order to run them in parallel
                if len(restrictions) > 1:
                    # multiple targets are restricted to a single scanning scope
                    scopes = {scope for scope, restrict in restrictions}
                    if len(scopes) > 1:
                        scan_scopes = ', '.join(sorted(map(str, scopes)))
                        parser.error(f'targets specify multiple scan scope levels: {scan_scopes}')

                    combined_restrict = boolean.OrRestriction(*(r for s, r in restrictions))
                    restrictions = [(scopes.pop(), combined_restrict)]
        else:
            if namespace.cwd in namespace.target_repo:
                scope, restrict = _path_restrict(namespace.cwd, namespace.target_repo)
            else:
                scope, restrict = base.repo_scope, packages.AlwaysTrue
            restrictions = [(scope, restrict)]

    # only run version scope checks when using a package filter
    if namespace.filter is not None:
        namespace.enabled_checks = (
            c for c in namespace.enabled_checks if c.scope is base.version_scope)

    # pull scan scope from the given restriction targets
    restrictions = iter(restrictions)
    try:
        scan_scope, restrict = next(restrictions)
    except StopIteration:
        parser.error('no targets piped in')
    namespace.restrictions = chain([(scan_scope, restrict)], restrictions)

    # filter enabled checks based on the scanning scope
    namespace.enabled_checks = [
        check for check in namespace.enabled_checks
        if _selected_check(namespace, scan_scope, check.scope)
    ]

    if not namespace.enabled_checks:
        parser.error(f'no matching checks available for {scan_scope} scope')

    addons = base.get_addons(namespace.enabled_checks)

    try:
        for addon in addons:
            addon.check_args(parser, namespace)
    except argparse.ArgumentError as e:
        if namespace.debug:
            raise
        parser.error(str(e))

    namespace.addons = addons


def _selected_check(options, scan_scope, scope):
    """Verify check scope against current scan scope to determine check activation."""
    if scope == 0:
        if not options.selected_scopes:
            if scan_scope is base.repo_scope or scope is scan_scope:
                # Allow repo scans or cwd scope to trigger location specific checks.
                return True
        elif scope in options.selected_scopes:
            # Allow checks with special scopes to be run when specifically
            # requested, e.g. eclass-only scanning.
            return True
    elif scan_scope > 0 and scope >= scan_scope:
        # Only run pkg-related checks at or below the current scan scope level, if
        # pkg scanning is requested, e.g. skip repo level checks when scanning at
        # package level.
        return True
    elif options.commits and scan_scope != 0 and scope is base.commit_scope:
        # Only enable commit-related checks when --commits is specified.
        return True
    return False


@scan.bind_main_func
def _scan(options, out, err):
    ret = []
    with ExitStack() as stack:
        reporter = options.reporter(out)
        for c in options.pop('contexts') + [reporter]:
            stack.enter_context(c)
        for scan_scope, restrict in options.restrictions:
            pipe = Pipeline(options, scan_scope, restrict)
            ret.append(reporter(pipe))
    return int(any(ret))


cache = subparsers.add_parser(
    'cache', description='perform cache operations',
    docs="""
        Various types of caches are used by pkgcheck. This command supports
        running operations on them including updates and removals.
    """)
cache.add_argument(
    '--cache-dir', type=arghparse.create_dir, default=const.USER_CACHE_DIR,
    help='directory to use for storing cache files')
cache_actions = cache.add_mutually_exclusive_group()
cache_actions.add_argument(
    '-l', '--list', dest='list_cache', action='store_true',
    help='list available caches')
cache_actions.add_argument(
    '-u', '--update', dest='update_cache', action='store_true',
    help='update caches')
cache_actions.add_argument(
    '-r', '--remove', dest='remove_cache', action='store_true',
    help='forcibly remove caches')
cache.add_argument(
    '-f', '--force', dest='force_cache', action='store_true',
    help='forcibly update/remove caches')
cache.add_argument(
    '-n', '--dry-run', action='store_true',
    help='dry run without performing any changes')
cache.add_argument(
    '-t', '--type', dest='cache', action=argparsers.CacheNegations,
    help='target cache types')


@cache.bind_pre_parse
def _setup_cache_addons(parser, namespace):
    """Load all addons using caches and their argparser changes before parsing."""
    for addon in base.get_addons(CachedAddon.caches):
        addon.mangle_argparser(parser)


@cache.bind_final_check
def _validate_cache_args(parser, namespace):
    enabled_caches = {k for k, v in namespace.cache.items() if v}
    cache_addons = (
        addon for addon in CachedAddon.caches
        if addon.cache.type in enabled_caches)
    # sort caches by type
    namespace.cache_addons = sorted(cache_addons, key=lambda x: x.cache.type)

    namespace.target_repo = namespace.config.get_default('repo')
    try:
        for addon in namespace.cache_addons:
            addon.check_args(parser, namespace)
    except argparse.ArgumentError as e:
        if namespace.debug:
            raise
        parser.error(str(e))

    namespace.enabled_caches = enabled_caches


@cache.bind_main_func
def _cache(options, out, err):
    if options.remove_cache:
        cache_obj = CachedAddon(options)
        cache_obj.remove_caches()
    elif options.update_cache:
        for addon in options.pop('cache_addons'):
            init_addon(addon, options)
    else:
        # list existing caches
        cache_obj = CachedAddon(options)
        repos_dir = pjoin(options.cache_dir, 'repos')
        for cache_type in sorted(options.enabled_caches):
            paths = cache_obj.existing_caches[cache_type]
            if paths:
                out.write(out.fg('yellow'), f'{cache_type} caches: ', out.reset)
            for path in paths:
                repo = str(path.parent)[len(repos_dir):]
                # non-path repo ids get path separator stripped
                if repo.count(os.sep) == 1:
                    repo = repo.lstrip(os.sep)
                out.write(repo)

    return 0


replay = subparsers.add_parser(
    'replay', parents=(reporter_argparser,),
    description='replay result streams',
    docs="""
        Replay previous result streams, feeding the results into a reporter.
        Currently supports replaying streams from PickleStream or JsonStream
        reporters.

        Useful if you need to delay acting on results until it can be done in
        one minimal window, e.g. updating a database, or want to generate
        several different reports.
    """)
replay.add_argument(
    dest='results', metavar='FILE',
    type=arghparse.FileType('rb'), help='path to serialized results file')


@replay.bind_main_func
def _replay(options, out, err):
    # assume JSON encoded file, fallback to pickle format
    processed = 0
    exc = None
    with options.reporter(out) as reporter:
        try:
            for result in reporters.JsonStream.from_iter(options.results):
                reporter.report(result)
                processed += 1
        except reporters.DeserializationError as e:
            if not processed:
                options.results.seek(0)
                try:
                    for result in reporters.PickleStream.from_file(options.results):
                        reporter.report(result)
                        processed += 1
                except reporters.DeserializationError as e:
                    exc = e
            else:
                exc = e

    if exc:
        if not processed:
            raise UserException('invalid or unsupported replay file')
        raise UserException(
            f'corrupted results file {options.results.name!r}: {exc}')

    return 0


def dump_docstring(out, obj, prefix=None):
    if prefix is not None:
        out.first_prefix.append(prefix)
        out.later_prefix.append(prefix)
    try:
        if obj.__doc__ is None:
            raise ValueError('no docs for {obj!r}')

        # Docstrings start with an unindented line. Everything
        # else is consistently indented.
        lines = obj.__doc__.split('\n')
        firstline = lines[0].strip()
        # Some docstrings actually start on the second line.
        if firstline:
            out.write(firstline)
        if len(lines) > 1:
            for line in textwrap.dedent('\n'.join(lines[1:])).split('\n'):
                out.write(line)
        else:
            out.write()
    finally:
        if prefix is not None:
            out.first_prefix.pop()
            out.later_prefix.pop()


@decorate_forced_wrapping()
def display_keywords(out, options):
    if options.verbosity < 1:
        out.write('\n'.join(sorted(objects.KEYWORDS)), wrap=False)
    else:
        scopes = defaultdict(set)
        for keyword in objects.KEYWORDS.values():
            scopes[keyword.scope].add(keyword)

        for scope in reversed(sorted(scopes)):
            out.write(out.bold, f"{str(scope).capitalize()} scope:")
            out.write()
            keywords = sorted(scopes[scope], key=attrgetter('__name__'))

            try:
                out.first_prefix.append('  ')
                out.later_prefix.append('  ')
                for keyword in keywords:
                    out.write(out.fg(keyword.color), keyword.__name__, out.reset, ':')
                    dump_docstring(out, keyword, prefix='  ')
            finally:
                out.first_prefix.pop()
                out.later_prefix.pop()


@decorate_forced_wrapping()
def display_checks(out, options):
    if options.verbosity < 1:
        out.write('\n'.join(sorted(objects.CHECKS)), wrap=False)
    else:
        d = defaultdict(list)
        for x in objects.CHECKS.values():
            d[x.__module__].append(x)

        for module_name in sorted(d):
            out.write(out.bold, f"{module_name}:")
            out.write()
            checks = d[module_name]
            checks.sort(key=attrgetter('__name__'))

            try:
                out.first_prefix.append('  ')
                out.later_prefix.append('  ')
                for check in checks:
                    out.write(out.fg('yellow'), check.__name__, out.reset, ':')
                    dump_docstring(out, check, prefix='  ')

                    # output result types that each check can generate
                    keywords = []
                    for r in sorted(check.known_results, key=attrgetter('__name__')):
                        keywords.extend([out.fg(r.color), r.__name__, out.reset, ', '])
                    keywords.pop()
                    out.write(*(['  (known results: '] + keywords + [')']))
                    out.write()

            finally:
                out.first_prefix.pop()
                out.later_prefix.pop()


@decorate_forced_wrapping()
def display_reporters(out, options):
    if options.verbosity < 1:
        out.write('\n'.join(sorted(objects.REPORTERS)), wrap=False)
    else:
        out.write("reporters:")
        out.write()
        out.first_prefix.append('  ')
        out.later_prefix.append('  ')
        for reporter in sorted(objects.REPORTERS.values(), key=attrgetter('__name__')):
            out.write(out.bold, out.fg('yellow'), reporter.__name__)
            dump_docstring(out, reporter, prefix='  ')


show = subparsers.add_parser('show', description='show various pkgcheck info')
list_options = show.add_argument_group('list options')
output_types = list_options.add_mutually_exclusive_group()
output_types.add_argument(
    '-k', '--keywords', action='store_true', default=False,
    help='show available warning/error keywords',
    docs="""
        List all available keywords.

        Use -v/--verbose to show keywords sorted into the scope they run at
        (repository, category, package, or version) along with their
        descriptions.
    """)
output_types.add_argument(
    '-c', '--checks', action='store_true', default=False,
    help='show available checks',
    docs="""
        List all available checks.

        Use -v/--verbose to show descriptions and possible keyword results for
        each check.
    """)
output_types.add_argument(
    '-s', '--scopes', action='store_true', default=False,
    help='show available keyword/check scopes',
    docs="""
        List all available keyword and check scopes.

        Use -v/--verbose to show scope descriptions.
    """)
output_types.add_argument(
    '-r', '--reporters', action='store_true', default=False,
    help='show available reporters',
    docs="""
        List all available reporters.

        Use -v/--verbose to show reporter descriptions.
    """)
output_types.add_argument(
    '-C', '--caches', action='store_true', default=False,
    help='show available caches',
    docs="""
        List all available cache types.

        Use -v/--verbose to show more cache information.
    """)


@show.bind_main_func
def _show(options, out, err):
    if options.checks:
        display_checks(out, options)
    elif options.scopes:
        if options.verbosity < 1:
            out.write('\n'.join(base.scopes))
        else:
            for name, scope in base.scopes.items():
                out.write(f'{name} -- {scope.desc} scope')
    elif options.reporters:
        display_reporters(out, options)
    elif options.caches:
        if options.verbosity < 1:
            caches = sorted(map(attrgetter('type'), CachedAddon.caches.values()))
            out.write('\n'.join(caches))
        else:
            for cache in sorted(CachedAddon.caches.values(), key=attrgetter('type')):
                out.write(f'{cache.type} -- file: {cache.file}, version: {cache.version}')
    else:
        # default to showing keywords if no output option is selected
        display_keywords(out, options)

    return 0
