import argparse
import os
import shlex
from contextlib import ExitStack

from pkgcore import const as pkgcore_const
from pkgcore.repository import errors as repo_errors
from pkgcore.repository import multiplex
from pkgcore.restrictions import packages
from pkgcore.restrictions.util import collect_package_restrictions
from pkgcore.util import parserestrict
from snakeoil.cli import arghparse
from snakeoil.osutils import pjoin

from .. import base, const, objects
from ..base import PkgcheckUserException
from ..cli import ConfigFileParser
from ..pipeline import Pipeline
from . import argparse_actions
from .argparsers import repo_argparser, reporter_argparser

config_argparser = arghparse.ArgumentParser(suppress=True)
config_options = config_argparser.add_argument_group('config options')
config_options.add_argument(
    '--config', action=argparse_actions.ConfigArg, dest='config_file',
    help='use custom pkgcheck scan settings file',
    docs="""
        Load custom pkgcheck scan settings from a given file.

        Note that custom user settings override all other system and repo-level
        settings.

        It's also possible to disable all types of settings loading by
        specifying an argument of 'false' or 'no'.
    """)


scan = arghparse.ArgumentParser(
    prog='pkgcheck scan', description='scan targets for QA issues',
    parents=(config_argparser, repo_argparser, reporter_argparser))
scan.add_argument(
    'targets', metavar='TARGET', nargs='*', action=arghparse.ParseNonblockingStdin,
    help='optional targets')

main_options = scan.add_argument_group('main options')
main_options.add_argument(
    '-f', '--filter',
    action=arghparse.Delayed, target=argparse_actions.FilterArgs, priority=99,
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
    '-j', '--jobs', type=arghparse.positive_int,
    help='number of checks to run in parallel',
    docs="""
        Number of checks to run in parallel, defaults to using all available
        processors.
    """)
main_options.add_argument(
    '-t', '--tasks', type=arghparse.positive_int,
    help='number of asynchronous tasks to run concurrently',
    docs="""
        Number of asynchronous tasks to run concurrently (defaults to 5 * CPU count).
    """)
main_options.add_argument(
    '--cache', action=argparse_actions.CacheNegations,
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
    action=argparse_actions.ExitArgs, nargs='?', default=(),
    help='checksets, checks, or keywords that trigger an error exit status',
    docs="""
        Comma-separated list of checksets, checks, or keywords to enable and
        disable that trigger an exit status failure. Checkset and check
        arguments expand into their respective keyword sets.

        If no arguments or only disabled arguments are passed, enabled
        arguments are the set of error level keywords.

        To specify disabled keywords prefix them with ``-``. Also, the special
        arguments of ``error``, ``warning``, ``style``, and ``info`` correspond
        to the related keyword groups.
    """)


check_options = scan.add_argument_group('check selection')
check_options.add_argument(
    '--net', nargs=0,
    action=arghparse.Delayed, target=argparse_actions.EnableNet, priority=-1,
    help='enable checks that require network access')
check_options.add_argument(
    '-C', '--checksets', metavar='CHECKSET', action=argparse_actions.ChecksetArgs,
    help='scan using a configured set of check/keyword args',
    docs="""
        Comma-separated list of checksets to enable and disable for
        scanning.

        The special argument of ``all`` corresponds to the list of all checks.
        Therefore, to forcibly enable all checks use ``-C all``.

        All network-related checks (which are disabled by default)
        can be enabled using ``-C net``. This allows for easily running only
        network checks without having to explicitly list them.
    """)
check_options.add_argument(
    '-s', '--scopes', metavar='SCOPE', dest='selected_scopes', default=(),
    action=arghparse.Delayed, target=argparse_actions.ScopeArgs, priority=51,
    help='limit checks to run by scope',
    docs="""
        Comma-separated list of scopes to enable and disable for scanning. Any
        scopes specified in this fashion will affect the checks that get
        run. For example, running pkgcheck with only the repo scope
        enabled will cause only repo-level checks to run.

        Available scopes: %s
    """ % (', '.join(base.scopes)))
check_options.add_argument(
    '-c', '--checks', metavar='CHECK', dest='selected_checks', default=(),
    action=arghparse.Delayed, target=argparse_actions.CheckArgs, priority=52,
    help='limit checks to run',
    docs="""
        Comma-separated list of checks to enable and disable for
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
    action=arghparse.Delayed, target=argparse_actions.KeywordArgs, priority=53,
    help='limit keywords to scan for',
    docs="""
        Comma-separated list of keywords to enable and disable for
        scanning. Any keywords specified in this fashion will be the
        only keywords that get reported, skipping any disabled keywords.

        To specify disabled keywords prefix them with ``-``. Note that when
        starting the argument list with a disabled keyword an equals sign must
        be used, e.g. ``-k=-keyword``, otherwise the disabled keyword argument is
        treated as an option.

        The special arguments of ``error``, ``warning``, ``style``, and
        ``info`` correspond to the related keyword groups. For example, to only
        scan for errors use ``-k error``.

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
    namespace.pkg_scan = False


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
    # always load settings from bundled config
    namespace = config_parser.parse_config_options(
        namespace, configs=[const.BUNDLED_CONF_FILE])

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
    profiles_base = os.path.realpath(repo.config.profiles_base)

    for target in targets:
        path = os.path.realpath(target)
        # prefer path restrictions if it's in the target repo
        if os.path.exists(path) and path in repo:
            if path.endswith('.eclass'):
                # direct eclass file targets
                yield base.eclass_scope, os.path.basename(path)[:-7]
            elif path.startswith(profiles_base) and path[len(profiles_base):]:
                if os.path.isdir(path):
                    # descend into profiles dir targets
                    for root, _dirs, files in os.walk(path):
                        paths = {pjoin(root, x) for x in files}
                        yield base.profile_node_scope, paths
                else:
                    # direct profiles file targets
                    yield base.profile_node_scope, path
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


@scan.bind_delayed_default(1000, 'jobs')
def _default_jobs(namespace, attr):
    """Extract jobs count from MAKEOPTS."""
    parser = argparse.ArgumentParser()
    parser.add_argument('-j', '--jobs', type=arghparse.positive_int, default=os.cpu_count())
    makeopts, _ = parser.parse_known_args(shlex.split(os.getenv('MAKEOPTS', '')))
    setattr(namespace, attr, makeopts.jobs)


@scan.bind_delayed_default(1001, 'tasks')
def _default_tasks(namespace, attr):
    """Set based on jobs count."""
    setattr(namespace, attr, namespace.jobs * 5)


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
        # Generate restrictions for all targets, blocking scanning until
        # piped-in targets are read. This avoids pickling overhead and having
        # to support pickleable check instances under the parallelized check
        # running pipeline.
        restrictions = list(generate_restricts(namespace.target_repo, namespace.targets))
        if not restrictions:
            raise PkgcheckUserException('no targets')
    else:
        if namespace.cwd in namespace.target_repo:
            scope, restrict = _path_restrict(namespace.cwd, namespace.target_repo)
            if scope == base.package_scope:
                namespace.pkg_scan = True
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
        pipe = Pipeline(options)
        for result in pipe:
            reporter.report(result)
    return int(bool(pipe.errors))
