"""
pkgcore-based QA utility

pkgcheck is a QA utility based on **pkgcore**\\(5) similar to **repoman**\\(1)
from portage.
"""

import argparse
from functools import partial
from itertools import chain
from json.decoder import JSONDecodeError
from operator import attrgetter
import logging
import os
import sys
import textwrap

from pkgcore import const as pkgcore_const
from pkgcore.ebuild import repository
from pkgcore.repository import multiplex
from pkgcore.restrictions import packages
from pkgcore.restrictions.values import StrExactMatch
from pkgcore.util import commandline, parserestrict
from snakeoil import pickling, formatters
from snakeoil.cli import arghparse
from snakeoil.formatters import decorate_forced_wrapping
from snakeoil.log import suppress_logging
from snakeoil.osutils import abspath, pjoin
from snakeoil.sequences import iflatten_instance
from snakeoil.sequences import unstable_unique
from snakeoil.strings import pluralism as _pl

from .. import base, feeds, const, reporters


pkgcore_config_opts = commandline.ArgumentParser(script=(__file__, __name__))
argparser = commandline.ArgumentParser(
    suppress=True, description=__doc__, parents=(pkgcore_config_opts,),
    script=(__file__, __name__))
# TODO: rework pkgcore's config system to allow more lazy loading
argparser.set_defaults(profile_override=pjoin(pkgcore_const.DATA_PATH, 'stubrepo/profiles/default'))
subparsers = argparser.add_subparsers(description="check applets")


reporter_opts = commandline.ArgumentParser(suppress=True)
reporter_opts.add_argument(
    '-R', '--reporter', action='store', default=None,
    help='use a non-default reporter',
    docs="""
        Select a reporter to use for output.

        Use ``pkgcheck show --reporters`` to see available options.
    """)
@reporter_opts.bind_parse_priority(20)
def _setup_reporter(namespace):
    if namespace.reporter is None:
        reporters = sorted(
            const.REPORTERS.values(), key=attrgetter('priority'), reverse=True)
        namespace.reporter = reporters[0]
    else:
        try:
            namespace.reporter = const.REPORTERS[namespace.reporter]
        except KeyError:
            available = ', '.join(const.REPORTERS.keys())
            argparser.error(
                f"no reporter matches {namespace.reporter!r} "
                f"(available: {available})")


# These are all set based on other options, so have no default setting.
scan = subparsers.add_parser(
    'scan', parents=(reporter_opts,), description='scan targets for QA issues')
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

check_options = scan.add_argument_group('check selection')
check_options.add_argument(
    '-c', '--checks', metavar='CHECK', action='csv_negations', dest='selected_checks',
    help='limit checks to regex or package/class matching (comma-separated list)')
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

        The special arguments of ``errors`` and ``warnings`` correspond to the
        lists of error and warning keywords, respectively. Therefore, to only
        scan for errors and ignore all QA warnings use ``-k errors``.

        Use ``pkgcheck show --keywords`` or the list below to see available options.
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
    """ % (', '.join(base.known_scopes)))


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

    if namespace.target_repo is None:
        # we have no target repo so try to guess one
        target_repo = None
        target_dir = cwd

        # pull a target directory from target args if they're path-based
        if namespace.targets and os.path.exists(namespace.targets[0]):
            target = os.path.abspath(namespace.targets[0])
            if os.path.isfile(target):
                target = os.path.dirname(target)
            target_dir = target

        with suppress_logging():
            # determine target repo from the target directory
            for repo in namespace.domain.ebuild_repos_raw:
                if target_dir in repo:
                    target_repo = repo
                    break
            else:
                # determine if CWD is inside an unconfigured repo
                target_repo = namespace.domain.find_repo(
                    target_dir, config=namespace.config, configure=False)

        if target_repo is None:
            # fallback to the default repo
            target_repo = namespace.config.get_default('repo')
        elif len(namespace.targets) == 1 and (
                os.path.abspath(namespace.targets[0]) == target_repo.location):
            # reset targets so the entire repo is scanned
            namespace.targets = []

        namespace.target_repo = target_repo

    # use filtered repo if filtering is enabled
    if namespace.filtered:
        namespace.target_repo = namespace.domain.ebuild_repos[str(namespace.target_repo)]

    # search_repo is a multiplex of target_repo and its masters, make sure
    # they're configured properly in metadata/layout.conf. This is used for
    # things like visibility checks (it is passed to the checkers in "start").
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

        def limiters():
            for target in namespace.targets:
                if os.path.exists(target):
                    try:
                        yield repo.path_restrict(target)
                    except ValueError as e:
                        parser.error(e)
                else:
                    try:
                        yield parserestrict.parse_match(target)
                    except parserestrict.ParseError as e:
                        parser.error(e)
        namespace.limiters = limiters()
    else:
        repo_base = getattr(namespace.target_repo, 'location', None)
        if not repo_base:
            parser.error(
                'Either specify a target repo that is not multi-tree or '
                'one or more extended atoms to scan '
                '("*" for the entire repo).')
        if cwd not in namespace.target_repo:
            namespace.limiters = [packages.AlwaysTrue]
        else:
            namespace.limiters = [packages.AndRestriction(
                *namespace.target_repo.path_restrict(cwd))]

    if namespace.checkset is None:
        namespace.checkset = namespace.config.get_default('pkgcheck_checkset')
    if namespace.checkset is not None:
        namespace.enabled_checks = list(namespace.checkset.filter(namespace.enabled_checks))

    if namespace.selected_scopes is not None:
        disabled_scopes, enabled_scopes = namespace.selected_scopes

        # validate selected scopes
        selected_scopes = set(disabled_scopes + enabled_scopes)
        unknown_scopes = selected_scopes - set(base.known_scopes.keys())
        if unknown_scopes:
            parser.error('unknown scope%s: %s (available scopes: %s)' % (
                _pl(unknown_scopes), ', '.join(map(repr, unknown_scopes)), ', '.join(base.known_scopes.keys())))

        # convert scopes to keyword lists
        disabled_keywords = [
            k.__name__ for s in disabled_scopes for k in const.KEYWORDS.values()
            if k.threshold == base.known_scopes[s].threshold]
        enabled_keywords = [
            k.__name__ for s in enabled_scopes for k in const.KEYWORDS.values()
            if k.threshold == base.known_scopes[s].threshold]

        # filter outputted keywords
        namespace.enabled_keywords = base.filter_update(
            namespace.enabled_keywords, enabled_keywords, disabled_keywords)

    if namespace.selected_keywords is not None:
        disabled_keywords, enabled_keywords = namespace.selected_keywords

        errors = (k for k, v in const.KEYWORDS.items() if issubclass(v, base.Error))
        warnings = (k for k, v in const.KEYWORDS.items() if issubclass(v, base.Warning))

        alias_map = {'errors': errors, 'warnings': warnings}
        replace_aliases = lambda x: alias_map.get(x, [x])

        # expand keyword aliases to keyword lists
        disabled_keywords = list(chain.from_iterable(map(replace_aliases, disabled_keywords)))
        enabled_keywords = list(chain.from_iterable(map(replace_aliases, enabled_keywords)))

        # validate selected keywords
        selected_keywords = set(disabled_keywords + enabled_keywords)
        available_keywords = set(const.KEYWORDS.keys())
        unknown_keywords = selected_keywords - available_keywords
        if unknown_keywords:
            parser.error("unknown keyword%s: %s (use 'pkgcheck show --keywords' to show valid keywords)" % (
                _pl(unknown_keywords), ', '.join(map(repr, unknown_keywords))))

        # filter outputted keywords
        namespace.enabled_keywords = base.filter_update(
            namespace.enabled_keywords, enabled_keywords, disabled_keywords)

    namespace.filtered_keywords = set(namespace.enabled_keywords)
    if namespace.filtered_keywords == set(const.KEYWORDS.values()):
        namespace.filtered_keywords = None

    disabled_checks, enabled_checks = ((), ())
    if namespace.selected_checks is not None:
        disabled_checks, enabled_checks = namespace.selected_checks
        # validate selected checks
        selected_checks = set(disabled_checks + enabled_checks)
        available_checks = set(const.CHECKS.keys())
        unknown_checks = selected_checks - available_checks
        if unknown_checks:
            parser.error("unknown check%s: %s (use 'pkgcheck show --checks' to show valid checks)" % (
                _pl(unknown_checks), ', '.join(map(repr, unknown_checks))))
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
    reporter = options.reporter(
        out, keywords=options.filtered_keywords, verbosity=options.verbosity)

    addons_map = {}

    def init_addon(klass):
        res = addons_map.get(klass)
        if res is not None:
            return res
        deps = list(init_addon(dep) for dep in klass.required_addons)
        res = addons_map[klass] = klass(options, *deps)
        return res

    for addon in options.addons:
        # Ignore the return value, we just need to populate addons_map.
        init_addon(addon)

    if options.verbosity > 1:
        err.write(
            f"target repo: {options.target_repo.repo_id!r} "
            f"at {options.target_repo.location!r}")
        for filterer in options.limiters:
            err.write('limiter: ', filterer)
        debug = logging.debug
    else:
        debug = None

    transforms = list(const.TRANSFORMS.values())
    sinks = [x for x in addons_map.values() if isinstance(x, base.Check)]

    if not sinks:
        err.write(f'{scan.prog}: no matching checks available for current scope')
        return

    raw_sources = {}
    required_sources = {check.source for check in options.enabled_checks}
    for source in required_sources:
        if isinstance(source, tuple):
            source_cls, args = source
        else:
            source_cls = source
            args = ()
        addons = [addons_map.get(cls, cls(options)) for cls in source_cls.required_addons]
        raw_sources[source] = partial(source_cls, *args, options, *addons)

    reporter.start()

    for filterer in options.limiters:
        sources = {raw: source(filterer) for raw, source in raw_sources.items()}
        bad_sinks, pipes = base.plug(sinks, transforms, sources, debug)
        if bad_sinks:
            # We want to report the ones that would work if this was a
            # full repo scan separately from the ones that are
            # actually missing transforms.
            bad_sinks = set(bad_sinks)
            full_scope = {
                raw: source(packages.AlwaysTrue) for raw, source in raw_sources.items()}
            really_bad, ignored = base.plug(sinks, transforms, full_scope)
            really_bad = set(really_bad)
            assert bad_sinks >= really_bad, \
                f'{really_bad - bad_sinks} unreachable with no limiters but reachable with?'
            for sink in really_bad:
                err.error(f'sink {sink} could not be connected (missing transforms?)')
            out_of_scope = bad_sinks - really_bad
            if options.verbosity > 1 and out_of_scope:
                err.warn('skipping repo checks (not a full repo scan)')

        if options.debug:
            err.write(f'Running {len(sinks) - len(bad_sinks)} tests')
        err.flush()

        for result in base.Pipeline(pipes).run():
            reporter.report(result)

    reporter.finish()

    # flush stdout first; if they're directing it all to a file, this makes
    # results not get the final message shoved in midway
    out.stream.flush()
    return 0


replay = subparsers.add_parser(
    'replay', parents=(reporter_opts,),
    description='replay results streams',
    docs="""
        Replay previous results streams from pkgcheck, feeding the results into
        a reporter. Currently supports replaying streams from pickled-based or
        JSON object reporters.

        Useful if you need to delay acting on results until it can be done in
        one minimal window (say updating a database), or want to generate
        several different reports without using a config defined multiplex
        reporter.
    """)
replay.add_argument(
    dest='results_file', type=arghparse.FileType('rb'), help='serialized results file')


@replay.bind_main_func
def _replay(options, out, err):
    reporter = options.reporter(out)
    reporter.start()
    # assume JSON encoded file, fallback to pickle format
    try:
        for line in options.results_file:
            result = reporters.JsonStream.from_json(line)
            reporter.report(result)
    except (JSONDecodeError, UnicodeDecodeError):
        options.results_file.seek(0)
        for count, item in enumerate(pickling.iter_stream(options.results_file)):
            reporter.report(item)
    reporter.finish()
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
    d = {}
    scope_map = {
        base.versioned_feed: base.version_scope,
        base.package_feed: base.package_scope,
        base.category_feed: base.category_scope,
        base.repository_feed: base.repository_scope,
    }
    for keyword in const.KEYWORDS.values():
        d.setdefault(scope_map[keyword.threshold], set()).add(keyword)

    if options.verbosity < 1:
        out.write('\n'.join(sorted(x.__name__ for s in d.values() for x in s)), wrap=False)
    else:
        scopes = tuple(x.desc for x in reversed(base.known_scopes.values()))
        for scope in reversed(sorted(d)):
            out.write(out.bold, f"{scopes[scope].capitalize()} scope:")
            out.write()
            keywords = sorted(d[scope], key=attrgetter('__name__'))

            try:
                out.first_prefix.append('  ')
                out.later_prefix.append('  ')
                for keyword in keywords:
                    out.write(out.fg(keyword.color.__get__(keyword)), keyword.__name__, out.reset, ':')
                    dump_docstring(out, keyword, prefix='  ')
            finally:
                out.first_prefix.pop()
                out.later_prefix.pop()


@decorate_forced_wrapping()
def display_checks(out, options):
    d = {}
    for x in const.CHECKS.values():
        d.setdefault(x.__module__, []).append(x)

    if options.verbosity < 1:
        out.write('\n'.join(sorted(x.__name__ for s in d.values() for x in s)), wrap=False)
    else:
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
                    results = []
                    for r in sorted(check.known_results, key=attrgetter('__name__')):
                        results.extend([out.fg(r.color.__get__(r)), r.__name__, out.reset, ', '])
                    results.pop()
                    out.write(*(['  (known results: '] + results + [')']))
                    out.write()

            finally:
                out.first_prefix.pop()
                out.later_prefix.pop()


@decorate_forced_wrapping()
def display_reporters(out, options, reporters):
    if options.verbosity < 1:
        out.write('\n'.join(sorted(x.__name__ for x in reporters)), wrap=False)
    else:
        out.write()
        out.write("reporters:")
        out.write()
        out.first_prefix.append('  ')
        out.later_prefix.append('  ')
        for reporter in sorted(reporters, key=attrgetter('__name__')):
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
            out.write('\n'.join(base.known_scopes.keys()))
        else:
            for name, scope in base.known_scopes.items():
                out.write(f'{name} -- {scope.desc} scope')

    if options.reporters:
        display_reporters(out, options, list(const.REPORTERS.values()))

    return 0
