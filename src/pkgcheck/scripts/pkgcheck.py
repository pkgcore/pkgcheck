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
from operator import attrgetter

from pkgcore import const as pkgcore_const
from pkgcore.repository import errors as repo_errors
from pkgcore.repository import multiplex
from pkgcore.restrictions import boolean, packages
from pkgcore.restrictions.util import collect_package_restrictions
from pkgcore.util import commandline, parserestrict
from snakeoil.cli import arghparse
from snakeoil.formatters import decorate_forced_wrapping
from snakeoil.osutils import pjoin

from .. import argparsers, base, const, objects, reporters
from ..addons import init_addon
from ..base import PkgcheckUserException
from ..caches import CachedAddon
from ..cli import ConfigFileParser
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

repo_argparser = commandline.ArgumentParser(suppress=True)
repo_options = repo_argparser.add_argument_group('repo options')
repo_options.add_argument(
    '-r', '--repo', metavar='REPO', dest='target_repo',
    action=commandline.StoreRepoObject, repo_type='ebuild-raw', allow_external_repos=True,
    help='target repo')

scan = subparsers.add_parser(
    'scan', parents=(config_argparser, repo_argparser, reporter_argparser,),
    description='scan targets for QA issues')
scan.add_argument(
    'targets', metavar='TARGET', nargs='*', action=arghparse.ParseNonblockingStdin,
    help='optional targets')

main_options = scan.add_argument_group('main options')
main_options.add_argument(
    '-f', '--filter',
    action=arghparse.Delayed, target=argparsers.FilterArgs, priority=99,
    help='limit targeted packages for scanning',
    docs="""
        Support limiting targeted packages for scanning using a chosen filter.

        If the 'latest' argument is used, only the latest package per slot of
        both VCS and non-VCS types will be scanned. This can either be
        specified individually in which case the filter will be applied
        globally to all checks or it can be applied to specific checksets,
        checks, or keywords using the syntax 'latest:ObjName' which would apply
        the filter to the keyword, check, or checkset named ObjName (in that
        order of precedence).

        By default, some checks have filtering enabled, e.g. various
        network-related checks are filtered to avoid redundant or unnecessary
        server requests. In order to forcibly disable all filtering use the
        'no' argument.
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
    '--exit', metavar='ITEM', dest='exit_keywords',
    action=argparsers.ExitArgs, nargs='?', default=(),
    help='checksets, checks, or keywords that trigger an error exit status (comma-separated list)',
    docs="""
        Comma separated list of checksets, checks, or keywords to enable and
        disable that trigger an exit status failure. Checkset and check
        arguments expand into their respective keyword sets.

        If no arguments or only disabled arguments are passed, enabled
        arguments are the set of error level keywords.

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
    '-C', '--checksets', metavar='CHECKSET', action=argparsers.ChecksetArgs,
    help='scan using a configured set of check/keyword args',
    docs="""
        Comma separated list of checksets to enable and disable for
        scanning.

        The special argument of ``all`` corresponds to the list of all checks.
        Therefore, to forcibly enable all checks use ``-C all``.

        All network-related checks (which are disabled by default)
        can be enabled using ``-C net``. This allows for easily running only
        network checks without having to explicitly list them.
    """)
check_options.add_argument(
    '-s', '--scopes', metavar='SCOPE', dest='selected_scopes', default=(),
    action=arghparse.Delayed, target=argparsers.ScopeArgs, priority=51,
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
    action=arghparse.Delayed, target=argparsers.CheckArgs, priority=52,
    help='limit checks to run (comma-separated list)',
    docs="""
        Comma separated list of checks to enable and disable for
        scanning. Any checks specified in this fashion will be the
        only checks that get run, skipping any disabled checks.

        To disable checks prefix them with ``-``. Note that when starting the
        argument list with a disabled check an equals sign must be used, e.g.
        ``-c=-check``, otherwise the disabled check argument is treated as an
        option.

        Additive arguments are also supported using the prefix ``+`` that adds
        to the default set of enabled checks. This is useful in order to enable
        optional checks in addition to the default set.

        Use ``pkgcheck show --checks`` see all available checks.
    """)
check_options.add_argument(
    '-k', '--keywords', metavar='KEYWORD', dest='selected_keywords', default=(),
    action=arghparse.Delayed, target=argparsers.KeywordArgs, priority=53,
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
    namespace.config_checksets = {}
    namespace.contexts = []


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
        namespace = config_parser.parse_config_options(
            namespace, configs=ConfigFileParser.default_configs)

    # TODO: Limit to parsing repo and targets options here so all args don't
    # have to be parsed twice, will probably require a custom snakeoil
    # arghparse method.
    # parse command line args to override config defaults
    namespace, _ = parser._parse_known_args(args, namespace)

    # Get the current working directory for repo detection and restriction
    # creation, fallback to the root dir if it's be removed out from under us.
    try:
        namespace.cwd = os.path.abspath(os.getcwd())
    except FileNotFoundError:
        namespace.cwd = const.DATA_PATH

    # if we have no target repo figure out what to use
    if namespace.target_repo is None:
        namespace.target_repo = _determine_target_repo(namespace)

    # determine if we're running in the gentoo repo or a clone
    namespace.gentoo_repo = 'gentoo' in namespace.target_repo.aliases

    # multiplex of target repo and its masters used for package existence queries
    namespace.search_repo = multiplex.tree(*namespace.target_repo.trees)

    if namespace.config_file is not False:
        # support loading repo-specific config settings from metadata/pkgcheck.conf
        repo_config_file = os.path.join(namespace.target_repo.location, 'metadata', 'pkgcheck.conf')
        configs = [repo_config_file]
        # custom user settings take precedence over previous configs
        if namespace.config_file:
            configs.append(namespace.config_file)
        namespace = config_parser.parse_config_options(namespace, configs=configs)

    # load repo-specific args from config if they exist
    namespace = config_parser.parse_config_sections(namespace, namespace.target_repo.aliases)

    return namespace, args


def generate_restricts(repo, targets):
    """Generate scanning restrictions from given targets."""
    eclasses = []
    profiles = []
    profiles_base = os.path.realpath(repo.config.profiles_base)

    for target in targets:
        path = os.path.realpath(target)
        # prefer path restrictions if it's in the target repo
        if os.path.exists(path) and path in repo:
            if path.endswith('.eclass'):
                # direct eclass file targets
                eclasses.append(os.path.basename(path)[:-7])
            elif path.startswith(profiles_base) and path[len(profiles_base):]:
                if os.path.isdir(path):
                    # descend into profiles dir targets
                    for root, _dirs, files in os.walk(path):
                        profiles.extend(pjoin(root, x) for x in files)
                else:
                    # direct profiles file targets
                    profiles.append(path)
            else:
                # generic repo path target
                yield _path_restrict(path, repo)
        else:
            try:
                # assume it's a package restriction
                restrict = parserestrict.parse_match(target)
                scope = _restrict_to_scope(restrict)
                yield scope, restrict
            except parserestrict.ParseError as e:
                # use path-based error for path-based targets
                if os.path.exists(path) or os.path.isabs(target):
                    raise PkgcheckUserException(
                        f"{repo.repo_id!r} repo doesn't contain: {target!r}")
                raise PkgcheckUserException(str(e))

    if eclasses:
        yield base.eclass_scope, frozenset(eclasses)
    if profiles:
        yield base.profile_node_scope, frozenset(profiles)


@scan.bind_delayed_default(1000, 'filter')
def _default_filter(namespace, attr):
    """Use source filtering for keywords requesting it by default."""
    setattr(namespace, attr, objects.KEYWORDS.filter)


@scan.bind_delayed_default(1000, 'enabled_checks')
def _default_enabled_checks(namespace, attr):
    """All non-optional checks are run by default."""
    setattr(namespace, attr, set(objects.CHECKS.default.values()))


@scan.bind_delayed_default(1000, 'filtered_keywords')
def _default_filtered_keywords(namespace, attr):
    """Enable all keywords to be shown by default."""
    setattr(namespace, attr, set(objects.KEYWORDS.values()))


@scan.bind_delayed_default(9999, 'restrictions')
def _determine_restrictions(namespace, attr):
    """Determine restrictions for untargeted scans and generate collapsed restriction for targeted scans."""
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
                    scan_scopes = ', '.join(sorted(s.desc for s in scopes))
                    raise PkgcheckUserException(
                        f'targets specify multiple scan scope levels: {scan_scopes}')

                combined_restrict = boolean.OrRestriction(*(r for s, r in restrictions))
                restrictions = [(scopes.pop(), combined_restrict)]
    else:
        if namespace.cwd in namespace.target_repo:
            scope, restrict = _path_restrict(namespace.cwd, namespace.target_repo)
        else:
            scope, restrict = base.repo_scope, packages.AlwaysTrue
        restrictions = [(scope, restrict)]

    setattr(namespace, attr, restrictions)


@scan.bind_main_func
def _scan(options, out, err):
    with ExitStack() as stack:
        reporter = options.reporter(out)
        for c in options.pop('contexts') + [reporter]:
            stack.enter_context(c)
        pipe = Pipeline(options, options.restrictions)
        for result in pipe:
            reporter.report(result)
    return int(bool(pipe.errors))


cache = subparsers.add_parser(
    'cache', parents=(repo_argparser,), description='perform cache operations',
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
    '-R', '--remove', dest='remove_cache', action='store_true',
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


@cache.bind_early_parse
def _setup_cache(parser, namespace, args):
    if namespace.target_repo is None:
        namespace.target_repo = namespace.config.get_default('repo')
    return namespace, args


@cache.bind_final_check
def _validate_cache_args(parser, namespace):
    enabled_caches = {k for k, v in namespace.cache.items() if v}
    cache_addons = (
        addon for addon in CachedAddon.caches
        if addon.cache.type in enabled_caches)
    # sort caches by type
    namespace.cache_addons = sorted(cache_addons, key=lambda x: x.cache.type)

    namespace.enabled_caches = enabled_caches


@cache.bind_main_func
def _cache(options, out, err):
    if options.remove_cache:
        cache_obj = CachedAddon(options)
        cache_obj.remove_caches()
    elif options.update_cache:
        for addon_cls in options.pop('cache_addons'):
            init_addon(addon_cls, options)
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
        Replay previous json result streams, feeding the results into a reporter.

        Useful if you need to delay acting on results until it can be done in
        one minimal window, e.g. updating a database, or want to generate
        several different reports.
    """)
replay.add_argument(
    dest='results', metavar='FILE',
    type=arghparse.FileType('rb'), help='path to serialized results file')


@replay.bind_main_func
def _replay(options, out, err):
    processed = 0

    with options.reporter(out) as reporter:
        try:
            for result in reporters.JsonStream.from_iter(options.results):
                reporter.report(result)
                processed += 1
        except reporters.DeserializationError as e:
            if not processed:
                raise PkgcheckUserException('invalid or unsupported replay file')
            raise PkgcheckUserException(
                f'corrupted results file {options.results.name!r}: {e}')

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
            out.write(out.bold, f'{scope.desc.capitalize()} scope:')
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
