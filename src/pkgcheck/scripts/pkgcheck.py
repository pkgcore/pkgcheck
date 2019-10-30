"""
pkgcore-based QA utility

pkgcheck is a QA utility based on **pkgcore**\\(5) that supports scanning
ebuild repositories for various issues.
"""

import argparse
import os
import sys
import textwrap
from collections import defaultdict
from functools import partial
from itertools import chain
from operator import attrgetter

from pkgcore import const as pkgcore_const
from pkgcore.repository import multiplex
from pkgcore.restrictions import boolean, packages
from pkgcore.restrictions.util import collect_package_restrictions
from pkgcore.util import commandline, parserestrict
from snakeoil.cli import arghparse
from snakeoil.cli.exceptions import UserException
from snakeoil.formatters import decorate_forced_wrapping
from snakeoil.log import suppress_logging
from snakeoil.osutils import abspath, pjoin
from snakeoil.strings import pluralism as _pl

from .. import base, const, pipeline, reporters, results
from ..addons import init_addon
from ..checks import init_checks
from ..log import logger

pkgcore_config_opts = commandline.ArgumentParser(script=(__file__, __name__))
argparser = commandline.ArgumentParser(
    suppress=True, description=__doc__, parents=(pkgcore_config_opts,),
    script=(__file__, __name__))
# TODO: rework pkgcore's config system to allow more lazy loading
argparser.set_defaults(profile_override=pjoin(pkgcore_const.DATA_PATH, 'stubrepo/profiles/default'))
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
@reporter_argparser.bind_parse_priority(20)
def _setup_reporter(namespace):
    if namespace.reporter is None:
        namespace.reporter = sorted(
            const.REPORTERS.values(), key=attrgetter('priority'), reverse=True)[0]
    else:
        try:
            namespace.reporter = const.REPORTERS[namespace.reporter]
        except KeyError:
            available = ', '.join(const.REPORTERS.keys())
            argparser.error(
                f"no reporter matches {namespace.reporter!r} "
                f"(available: {available})")

    if namespace.reporter is reporters.FormatReporter:
        if not namespace.format_str:
            argparser.error('missing or empty --format option required by FormatReporter')
        namespace.reporter = partial(namespace.reporter, namespace.format_str)
    elif namespace.format_str is not None:
        argparser.error('--format option is only valid when using FormatReporter')


def positive_int(x):
    n = int(x)
    if n < 1:
        raise argparse.ArgumentTypeError('must be >= 1')
    return n


# These are all set based on other options, so have no default setting.
scan = subparsers.add_parser(
    'scan', parents=(reporter_argparser,), description='scan targets for QA issues')
scan.set_defaults(forced_checks=[])
scan.add_argument(
    'targets', metavar='TARGET', nargs='*', help='optional target atom(s)')

main_options = scan.add_argument_group('main options')
main_options.add_argument(
    '-r', '--repo', metavar='REPO', dest='target_repo',
    action=commandline.StoreRepoObject, repo_type='ebuild-raw', allow_external_repos=True,
    help='repo to pull packages from')
main_options.add_argument(
    '--filtered', action='store_true', default=False,
    help="enable all license and visibility filtering for packages",
    docs="""
        Enable all package filtering mechanisms such as ACCEPT_KEYWORDS,
        ACCEPT_LICENSE, and package.mask.
    """)
main_options.add_argument(
    '-j', '--jobs', type=positive_int, default=os.cpu_count(),
    help='number of checks to run in parallel',
    docs="""
        Number of checks to run in parallel, defaults to using all available
        processors.
    """)
main_options.add_argument(
    '-t', '--tasks', type=positive_int, default=os.cpu_count() * 5,
    help='number of asynchronous tasks to run concurrently',
    docs="""
        Number of asynchronous tasks to run concurrently (defaults to 5 * CPU count).
    """)

check_options = scan.add_argument_group('check selection')
check_options.add_argument(
    '-c', '--checks', metavar='CHECK', action='csv_negations', dest='selected_checks',
    help='limit checks to run (comma-separated list)',
    docs="""
        Comma separated list of checks to enable and disable for
        scanning. Any checks specified in this fashion will be the
        only checks that get run, skipping any disabled checks.

        To specify disabled checks prefix them with ``-``. Note that when
        starting the argument list with a disabled check an equals sign must
        be used, e.g. ``-c=-check``, otherwise the disabled check argument is
        treated as an option.

        The special argument of ``all`` corresponds to the list of all checks,
        respectively. Therefore, to forcibly enable all checks use ``-c all``.

        Use ``pkgcheck show --checks`` see available options.
    """)
check_options.add_argument(
    '-C', '--checkset', metavar='CHECKSET', action=commandline.StoreConfigObject,
    config_type='pkgcheck_checkset',
    help='preconfigured set of checks to run')
check_options.add_argument(
    '-k', '--keywords', metavar='KEYWORD', action='csv_negations', dest='selected_keywords',
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
check_options.add_argument(
    '-s', '--scopes', metavar='SCOPE', action='csv_negations', dest='selected_scopes',
    help='limit keywords to scan for by scope (comma-separated list)',
    docs="""
        Comma separated list of scopes to enable and disable for scanning. Any
        scopes specified in this fashion will affect the keywords that get
        reported. For example, running pkgcheck with only the repo scope
        enabled will cause only repo-level keywords to be scanned for and
        reported.

        To specify disabled scopes prefix them with ``-`` similar to the
        -k/--keywords option.

        Available scopes: %s
    """ % (', '.join(base.scopes)))
check_options.add_argument(
    '--net', action='store_true',
    help='run checks that require internet access')


def add_addon(addon, addon_set):
    if addon not in addon_set:
        addon_set.add(addon)
        for dep in addon.required_addons:
            add_addon(dep, addon_set)


all_addons = set()
scan.plugin = scan.add_argument_group('plugin options')
for check in const.CHECKS.values():
    add_addon(check, all_addons)
for addon in all_addons:
    addon.mangle_argparser(scan)


def _determine_target_repo(namespace, parser, cwd):
    """Determine a target repo when none was explicitly selected.

    Returns a repository object if a matching one is found, otherwise None.
    """
    target_dir = cwd

    # pull a target directory from target args if they're path-based
    if namespace.targets and len(namespace.targets) == 1:
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
                    return repo

    with suppress_logging():
        # determine target repo from the target directory
        for repo in namespace.domain.ebuild_repos_raw:
            if target_dir in repo:
                return repo

    # determine if CWD is inside an unconfigured repo
    return namespace.domain.find_repo(
        target_dir, config=namespace.config, configure=False)


def _path_restrict(path, namespace):
    """Generate custom package restriction from a given path.

    This drops the repo restriction (initial entry in path restrictions)
    since runs can only be made against single repo targets so the extra
    restriction is redundant and breaks several custom sources involving
    raw pkgs (lacking a repo attr) or faked repos.
    """
    repo = namespace.target_repo
    restrictions = []
    try:
        restrictions = repo.path_restrict(path)[1:]
    except ValueError as e:
        raise UserException(str(e))
    if restrictions:
        return packages.AndRestriction(*restrictions)
    return packages.AlwaysTrue


def _restrict_to_scope(restrict):
    """Determine a given restriction's scope level."""
    for scope, attrs in (
            (base.version_scope, ['fullver', 'version', 'rev']),
            (base.package_scope, ['package']),
            (base.category_scope, ['category'])):
        if any(collect_package_restrictions(restrict, attrs)):
            return scope
    return base.repository_scope


@scan.bind_final_check
def _validate_args(parser, namespace):
    namespace.enabled_checks = list(const.CHECKS.values())
    namespace.enabled_keywords = list(const.KEYWORDS.values())

    # Get the current working directory for repo detection and restriction
    # creation, fallback to the root dir if it's be removed out from under us.
    try:
        cwd = abspath(os.getcwd())
    except FileNotFoundError as e:
        cwd = '/'

    # if we have no target repo figure out what to use
    if namespace.target_repo is None:
        target_repo = _determine_target_repo(namespace, parser, cwd)
        # fallback to the default repo
        if target_repo is None:
            target_repo = namespace.config.get_default('repo')
        namespace.target_repo = target_repo

    # use filtered repo if filtering is enabled
    if namespace.filtered:
        namespace.target_repo = namespace.domain.ebuild_repos[namespace.target_repo.repo_id]

    # determine if we're running in the gentoo repo or a clone
    namespace.gentoo_repo = 'gentoo' in namespace.target_repo.aliases

    # multiplex of target repo and its masters used for package existence queries
    namespace.search_repo = multiplex.tree(*namespace.target_repo.trees)

    if namespace.targets:
        repo = namespace.target_repo

        # read targets from stdin in a non-blocking manner
        if len(namespace.targets) == 1 and namespace.targets[0] == '-':
            def stdin():
                while True:
                    line = sys.stdin.readline()
                    if not line:
                        break
                    yield line.rstrip()
            namespace.targets = stdin()

        def restrictions():
            for target in namespace.targets:
                try:
                    r = parserestrict.parse_match(target)
                except parserestrict.ParseError as e:
                    if os.path.exists(target):
                        try:
                            r = _path_restrict(target, namespace)
                        except ValueError as e:
                            parser.error(e)
                    else:
                        parser.error(e)
                yield _restrict_to_scope(r), r

        # Collapse restrictions for passed in targets while keeping the
        # generator intact for piped in targets.
        namespace.restrictions = restrictions()
        if isinstance(namespace.targets, list):
            namespace.restrictions = list(namespace.restrictions)

            # collapse restrictions in order to run them in parallel
            if len(namespace.restrictions) > 1:
                # multiple targets are restricted to a single scanning scope
                scopes = {scope for scope, restrict in namespace.restrictions}
                if len(scopes) > 1:
                    scan_scopes = ', '.join(sorted(map(str, scopes)))
                    parser.error(f'targets specify multiple scan scope levels: {scan_scopes}')

                combined_restrict = boolean.OrRestriction(*(r for s, r in namespace.restrictions))
                namespace.restrictions = [(scopes.pop(), combined_restrict)]
    else:
        if cwd in namespace.target_repo:
            restrict = _path_restrict(cwd, namespace)
        else:
            restrict = packages.AlwaysTrue
        namespace.restrictions = [(_restrict_to_scope(restrict), restrict)]

    if namespace.checkset is None:
        namespace.checkset = namespace.config.get_default('pkgcheck_checkset')
    if namespace.checkset is not None:
        namespace.enabled_checks = list(namespace.checkset.filter(namespace.enabled_checks))

    if namespace.selected_scopes is not None:
        disabled_scopes, enabled_scopes = namespace.selected_scopes

        # validate selected scopes
        selected_scopes = set(disabled_scopes + enabled_scopes)
        unknown_scopes = selected_scopes - set(base.scopes)
        if unknown_scopes:
            unknown = ', '.join(map(repr, unknown_scopes))
            available = ', '.join(base.scopes)
            parser.error(
                f'unknown scope{_pl(unknown_scopes)}: '
                f'{unknown} (available scopes: {available})')

        disabled_scopes = {base.scopes[x] for x in disabled_scopes}
        enabled_scopes = {base.scopes[x] for x in enabled_scopes}

        # convert scopes to keyword lists
        disabled_keywords = [
            k.__name__ for k in const.KEYWORDS.values() if k.scope in disabled_scopes]
        enabled_keywords = [
            k.__name__ for k in const.KEYWORDS.values() if k.scope in enabled_scopes]

        # filter outputted keywords
        namespace.enabled_keywords = base.filter_update(
            namespace.enabled_keywords, enabled_keywords, disabled_keywords)

    if namespace.selected_keywords is not None:
        disabled_keywords, enabled_keywords = namespace.selected_keywords

        error = (k for k, v in const.KEYWORDS.items() if issubclass(v, results.Error))
        warning = (k for k, v in const.KEYWORDS.items() if issubclass(v, results.Warning))
        info = (k for k, v in const.KEYWORDS.items() if issubclass(v, results.Info))

        alias_map = {'error': error, 'warning': warning, 'info': info}
        replace_aliases = lambda x: alias_map.get(x, [x])

        # expand keyword aliases to keyword lists
        disabled_keywords = list(chain.from_iterable(map(replace_aliases, disabled_keywords)))
        enabled_keywords = list(chain.from_iterable(map(replace_aliases, enabled_keywords)))

        # validate selected keywords
        selected_keywords = set(disabled_keywords + enabled_keywords)
        available_keywords = set(const.KEYWORDS.keys())
        unknown_keywords = selected_keywords - available_keywords
        if unknown_keywords:
            unknown = ', '.join(map(repr, unknown_keywords))
            parser.error(f'unknown keyword{_pl(unknown_keywords)}: {unknown}')

        # filter outputted keywords
        namespace.enabled_keywords = base.filter_update(
            namespace.enabled_keywords, enabled_keywords, disabled_keywords)

    namespace.filtered_keywords = set(namespace.enabled_keywords)
    if namespace.filtered_keywords == set(const.KEYWORDS.values()):
        namespace.filtered_keywords = None

    disabled_checks, enabled_checks = ((), ())
    if namespace.selected_checks is not None:
        disabled_checks, enabled_checks = namespace.selected_checks
        available_checks = list(const.CHECKS.keys())

        alias_map = {'all': available_checks}
        replace_aliases = lambda x: alias_map.get(x, [x])

        # expand check aliases to check lists
        disabled_checks = list(chain.from_iterable(map(replace_aliases, disabled_checks)))
        enabled_checks = list(chain.from_iterable(map(replace_aliases, enabled_checks)))

        # overwrite selected checks with expanded aliases
        namespace.selected_checks = (disabled_checks, enabled_checks)

        # validate selected checks
        selected_checks = set(disabled_checks + enabled_checks)
        unknown_checks = selected_checks.difference(available_checks)
        if unknown_checks:
            unknown = ', '.join(map(repr, unknown_checks))
            parser.error(f'unknown check{_pl(unknown_checks)}: {unknown} ')
    elif namespace.filtered_keywords is not None:
        # enable checks based on enabled keyword -> check mapping
        enabled_checks = []
        for check, cls in const.CHECKS.items():
            if namespace.filtered_keywords.intersection(cls.known_results):
                enabled_checks.append(check)

    # filter checks to run
    if enabled_checks:
        whitelist = base.Whitelist(enabled_checks)
        namespace.enabled_checks = list(whitelist.filter(namespace.enabled_checks))
    if disabled_checks:
        blacklist = base.Blacklist(disabled_checks)
        namespace.enabled_checks = list(blacklist.filter(namespace.enabled_checks))

    # skip checks that may be disabled
    namespace.enabled_checks = [
        c for c in namespace.enabled_checks if not c.skip(namespace)]

    if not namespace.enabled_checks:
        parser.error('no active checks')

    namespace.addons = set()

    for check in namespace.enabled_checks:
        add_addon(check, namespace.addons)
    try:
        for addon in namespace.addons:
            addon.check_args(parser, namespace)
    except argparse.ArgumentError as e:
        if namespace.debug:
            raise
        parser.error(str(e))


@scan.bind_main_func
def _scan(options, out, err):
    enabled_checks, caches = init_checks(options.pop('addons'), options)

    if options.verbosity >= 1:
        msg = f'target repo: {options.target_repo.repo_id!r}'
        if options.target_repo.repo_id != options.target_repo.location:
            msg += f' at {options.target_repo.location!r}'
        err.write(msg)

    # force cache updates
    if caches:
        base.Cache.update_caches(options, caches)

    with options.reporter(out, verbosity=options.verbosity,
                          keywords=options.filtered_keywords) as reporter:
        # run git commit checks separately from pkg-related checks
        for (source, is_async), checks in enabled_checks.pop(base.commit_scope, {}).items():
            for result in pipeline.GitPipeline(options, source, checks):
                reporter.report(result)

        if enabled_checks:
            for scan_scope, restrict in options.restrictions:
                # Skip checks higher than the current scan scope level, e.g. skip repo
                # level checks when scanning at package level.
                pipes = [d for scope, d in enabled_checks.items() if scope <= scan_scope]
                if not pipes:
                    err.write(f'{scan.prog}: no matching checks available for current scope')
                    continue

                if options.verbosity >= 1:
                    err.write(f'Running {len(pipes)} tests')
                if options.debug:
                    err.write(f'restriction: {restrict}')
                err.flush()

                reporter(pipeline.Pipeline(options, scan_scope, pipes, restrict))

    return 0


cache = subparsers.add_parser(
    'cache', description='update/remove pkgcheck caches',
    docs="""
        Caches of various types are used by pkgcheck. This command allows the
        user to manually force cache updates or removals.
    """)
cache_actions = cache.add_mutually_exclusive_group()
cache_actions.add_argument(
    '-u', '--update', dest='update_cache', action='store_true',
    help='update caches')
cache_actions.add_argument(
    '-r', '--remove', dest='remove_cache', action='store_true',
    help='forcibly remove caches')
cache.add_argument(
    '-f', '--force', dest='force_cache', action='store_true',
    help='forcibly update/remove caches')

cache_addons = set()
cache.plugin = cache.add_argument_group()
for check in const.CHECKS.values():
    for addon in check.required_addons:
        if issubclass(addon, base.Cache):
            cache_addons.add(addon)
for addon in cache_addons:
    addon.mangle_argparser(cache.plugin)

@cache.bind_final_check
def _validate_args(parser, namespace):
    for addon in cache_addons:
        add_addon(addon, cache_addons)
    try:
        for addon in cache_addons:
            addon.check_args(parser, namespace)
    except argparse.ArgumentError as e:
        if namespace.debug:
            raise
        parser.error(str(e))


@cache.bind_main_func
def _cache(options, out, err):
    ret = 0
    caches = [init_addon(addon, options) for addon in cache_addons]
    if options.remove_cache:
        ret = base.Cache.remove_caches(options, caches)
    elif options.update_cache:
        ret = base.Cache.update_caches(options, caches)
    else:
        # list existing caches
        caches_map = defaultdict(list)
        for cache in caches:
            for repo in sorted(options.domain.ebuild_repos, key=attrgetter('repo_id')):
                cache_file = cache.cache_file(repo)
                if os.path.exists(cache_file):
                    caches_map[cache.cache_type].append(repo)
        for cache_type, repos in caches_map.items():
            out.write(f'{cache_type} caches: ', autoline=False)
            if options.verbosity < 1:
                out.write(', '.join(r.repo_id for r in repos))
            else:
                out.write('\n' + '\n'.join(f'  {cache.cache_file(repo)}' for repo in repos))

    return ret


replay = subparsers.add_parser(
    'replay', parents=(reporter_argparser,),
    description='replay results streams',
    docs="""
        Replay previous results streams from pkgcheck, feeding the results into
        a reporter. Currently supports replaying streams from pickle or JSON
        stream reporters.

        Useful if you need to delay acting on results until it can be done in
        one minimal window (say updating a database), or want to generate
        several different reports without using a config defined multiplex
        reporter.
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
            for result in reporters.JsonStream.from_file(options.results):
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
        out.write('\n'.join(sorted(const.KEYWORDS.keys())), wrap=False)
    else:
        scopes = defaultdict(set)
        for keyword in const.KEYWORDS.values():
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
        out.write('\n'.join(sorted(const.CHECKS.keys())), wrap=False)
    else:
        d = defaultdict(list)
        for x in const.CHECKS.values():
            d[x.__module__].append(x)

        for module_name in sorted(d):
            out.write(out.bold, f"{module_name}:")
            out.write()
            l = d[module_name]
            l.sort(key=attrgetter('__name__'))

            try:
                out.first_prefix.append('  ')
                out.later_prefix.append('  ')
                for check in l:
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
        out.write('\n'.join(sorted(const.REPORTERS.keys())), wrap=False)
    else:
        out.write()
        out.write("reporters:")
        out.write()
        out.first_prefix.append('  ')
        out.later_prefix.append('  ')
        for reporter in sorted(const.REPORTERS.values(), key=attrgetter('__name__')):
            out.write(out.bold, out.fg('yellow'), reporter.__name__)
            dump_docstring(out, reporter, prefix='  ')


show = subparsers.add_parser('show', description='show various pkgcheck info')
list_options = show.add_argument_group('list options')
output_types = list_options.add_mutually_exclusive_group()
output_types.add_argument(
    '--keywords', action='store_true', default=False,
    help='show available warning/error keywords',
    docs="""
        List all available keywords.

        Use -v/--verbose to show keywords sorted into the scope they run at
        (repository, category, package, or version) along with their
        descriptions.
    """)
output_types.add_argument(
    '--checks', action='store_true', default=False,
    help='show available checks',
    docs="""
        List all available checks.

        Use -v/--verbose to show descriptions and possible keyword results for
        each check.
    """)
output_types.add_argument(
    '--scopes', action='store_true', default=False,
    help='show available keyword/check scopes',
    docs="""
        List all available keyword and check scopes.

        Use -v/--verbose to show scope descriptions.
    """)
output_types.add_argument(
    '--reporters', action='store_true', default=False,
    help='show available reporters',
    docs="""
        List all available reporters.

        Use -v/--verbose to show reporter descriptions.
    """)
@show.bind_main_func
def _show(options, out, err):
    # default to showing keywords if no output option is selected
    list_option_selected = any(
        getattr(options, attr) for attr in
        ('keywords', 'checks', 'scopes', 'reporters'))
    if not list_option_selected:
        options.keywords = True

    if options.keywords:
        display_keywords(out, options)

    if options.checks:
        display_checks(out, options)

    if options.scopes:
        if options.verbosity < 1:
            out.write('\n'.join(base.scopes.keys()))
        else:
            for name, scope in base.scopes.items():
                out.write(f'{name} -- {scope.desc} scope')

    if options.reporters:
        display_reporters(out, options)

    return 0
