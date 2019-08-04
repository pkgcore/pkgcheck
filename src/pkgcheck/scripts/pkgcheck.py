"""
pkgcore-based QA utility

pkgcheck is a QA utility based on **pkgcore**\\(5) similar to **repoman**\\(1)
from portage.
"""

import argparse
from functools import partial
from itertools import chain
from operator import attrgetter

from pkgcore import const
from pkgcore.plugin import get_plugins, get_plugin
from pkgcore.util import commandline, parserestrict
from snakeoil.cli import arghparse
from snakeoil.demandload import demandload
from snakeoil.formatters import decorate_forced_wrapping
from snakeoil.osutils import abspath, pjoin
from snakeoil.sequences import unstable_unique
from snakeoil.strings import pluralism as _pl

from .. import plugins, base, feeds

demandload(
    'logging',
    'os',
    'sys',
    'textwrap',
    'pkgcore.config:errors@config_errors',
    'pkgcore.ebuild:repository',
    'pkgcore.restrictions:packages',
    'pkgcore.restrictions.values:StrExactMatch',
    'pkgcore.repository:multiplex',
    'snakeoil:pickling,formatters',
    'snakeoil.log:suppress_logging',
    'snakeoil.sequences:iflatten_instance',
    'pkgcheck:errors',
)


pkgcore_config_opts = commandline.ArgumentParser()
argparser = commandline.ArgumentParser(
    suppress=True, description=__doc__, parents=(pkgcore_config_opts,),
    script=(__file__, __name__))
# TODO: rework pkgcore's config system to allow more lazy loading
argparser.set_defaults(profile_override=pjoin(const.DATA_PATH, 'fakerepo/profiles/default'))
subparsers = argparser.add_subparsers(description="check applets", default='scan')

# These are all set based on other options, so have no default setting.
scan = subparsers.add_parser('scan', description='scan targets for QA issues')
scan.set_defaults(repo_bases=[])
scan.set_defaults(guessed_suite=False)
scan.set_defaults(default_suite=False)
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
    '-s', '--suite', action=commandline.StoreConfigObject,
    config_type='pkgcheck_suite',
    help='specify the configuration suite to use')
main_options.add_argument(
    '-R', '--reporter', action='store', default=None,
    help='use a non-default reporter',
    docs="""
        Select a reporter to use for scan output.

        Use 'pkgcheck show --reporters' to see available options.
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

        To specify disabled keywords prefix them with '-'. Note that when
        starting the argument list with a disabled keyword an equals sign must
        be used, e.g. -k=-keyword, otherwise the disabled keyword argument is
        treated as an option.

        The special arguments of 'errors' and 'warnings' correspond to the
        lists of error and warning keywords, respectively. Therefore, to only
        scan for errors and ignore all QA warnings use the 'errors' argument to
        -k/--keywords.

        Use 'pkgcheck show --keywords' or the list below to see available options.
    """)
check_options.add_argument(
    '-S', '--scopes', metavar='SCOPE', action='csv_negations', dest='selected_scopes',
    help='limit keywords to scan for by scope (comma-separated list)',
    docs="""
        Comma separated list of scopes to enable and disable for scanning. Any
        scopes specified in this fashion will affect the keywords that get
        reported. For example, running pkgcheck with only the 'repo' scope
        enabled will cause only repo-level keywords to be scanned for and
        reported.

        To specify disabled scopes prefix them with '-' the same as for
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
for check in get_plugins('check', plugins):
    add_addon(check, all_addons)
for addon in all_addons:
    addon.mangle_argparser(scan)

# XXX hack...
_known_checks = tuple(sorted(
    unstable_unique(get_plugins('check', plugins)),
    key=attrgetter('__name__')))
_known_keywords = tuple(sorted(
    unstable_unique(chain.from_iterable(
    check.known_results for check in _known_checks)),
    key=attrgetter('__name__')))


@scan.bind_final_check
def _validate_args(parser, namespace):
    namespace.enabled_checks = list(_known_checks)
    namespace.enabled_keywords = list(_known_keywords)
    cwd = abspath(os.getcwd())

    if namespace.suite is None:
        # No suite explicitly specified. Use the repo to guess the suite.
        if namespace.target_repo is None:
            # Not specified either. Try to find a repo our cwd is in.
            # The use of a dict here is a hack to deal with one
            # repo having multiple names in the configuration.
            candidates = {}
            for name, suite in namespace.config.pkgcheck_suite.items():
                repo = suite.target_repo
                if repo is None:
                    continue
                repo_base = getattr(repo, 'location', None)
                if repo_base is not None and cwd.startswith(repo_base):
                    candidates[repo] = name
            if len(candidates) == 1:
                namespace.guessed_suite = True
                namespace.target_repo = tuple(candidates)[0]
        if namespace.target_repo is not None:
            # We have a repo, now find a suite matching it.
            candidates = list(
                suite for suite in namespace.config.pkgcheck_suite.values()
                if suite.target_repo is namespace.target_repo)
            if len(candidates) == 1:
                namespace.guessed_suite = True
                namespace.suite = candidates[0]
        if namespace.suite is None:
            # If we have multiple candidates or no candidates we
            # fall back to the default suite.
            namespace.suite = namespace.config.get_default('pkgcheck_suite')
            namespace.default_suite = namespace.suite is not None
    if namespace.suite is not None:
        # We have a suite. Lift defaults from it for values that
        # were not set explicitly:
        if namespace.checkset is None:
            namespace.checkset = namespace.suite.checkset
        # If we were called with no atoms we want to force
        # cwd-based detection.
        if namespace.target_repo is None:
            if namespace.targets:
                namespace.target_repo = namespace.suite.target_repo
            elif namespace.suite.target_repo is not None:
                # No atoms were passed in, so we want to guess
                # what to scan based on cwd below. That only makes
                # sense if we are inside the target repo. We still
                # want to pick the suite's target repo if we are
                # inside it, in case there is more than one repo
                # definition with a base that contains our dir.
                repo_base = getattr(namespace.suite.target_repo, 'location', None)
                if repo_base is not None and cwd.startswith(repo_base):
                    namespace.target_repo = namespace.suite.target_repo

    if namespace.target_repo is None:
        # We have no target repo (not explicitly passed, not from a suite, not
        # from an earlier guess at the target_repo) so try to guess one.
        target_repo = None
        target_dir = cwd

        # pull a target directory from target args if they're path-based
        if namespace.targets and os.path.exists(namespace.targets[0]):
            target = namespace.targets[0]
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

        # fallback to the default repo
        if target_repo is None:
            try:
                target_repo = namespace.config.get_default('repo')
            except config_errors.ConfigurationError as e:
                parser.error(str(e))

        namespace.target_repo = target_repo

    # use filtered repo if filtering is enabled
    if namespace.filtered:
        namespace.target_repo = namespace.domain.ebuild_repos[str(namespace.target_repo)]

    if namespace.reporter is None:
        namespace.reporter = namespace.config.get_default(
            'pkgcheck_reporter_factory')
        if namespace.reporter is None:
            namespace.reporter = get_plugin('reporter', plugins)
        if namespace.reporter is None:
            parser.error(
                'no config defined reporter found, nor any default '
                'plugin based reporters')
    else:
        func = namespace.config.pkgcheck_reporter_factory.get(namespace.reporter)
        if func is None:
            func = list(base.Whitelist([namespace.reporter]).filter(
                get_plugins('reporter', plugins)))
            if not func:
                available = ', '.join(sorted(
                    x.__name__ for x in get_plugins('reporter', plugins)))
                parser.error(
                    f"no reporter matches {namespace.reporter!r} "
                    f"(available: {available})")
            elif len(func) > 1:
                reporters = tuple(sorted(f"{x.__module__}.{x.__name__}" for x in func))
                parser.error(
                    f"reporter {namespace.reporter!r} matched multiple reporters, "
                    f"must match one. {reporters!r}")
            func = func[0]
        namespace.reporter = func

    # search_repo is a multiplex of target_repo and its masters, make sure
    # they're configured properly in metadata/layout.conf. This is used for
    # things like visibility checks (it is passed to the checkers in "start").
    namespace.search_repo = multiplex.tree(*namespace.target_repo.trees)

    namespace.repo_bases = [abspath(repo.location) for repo in reversed(namespace.target_repo.trees)]

    namespace.default_target = None
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
                try:
                    yield parserestrict.parse_match(target)
                except parserestrict.ParseError as e:
                    if os.path.exists(target):
                        try:
                            yield repo.path_restrict(target)
                        except ValueError as e:
                            parser.error(e)
                    else:
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
            namespace.default_target = cwd

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
            k.__name__ for s in disabled_scopes for k in _known_keywords
            if k.threshold == base.known_scopes[s].threshold]
        enabled_keywords = [
            k.__name__ for s in enabled_scopes for k in _known_keywords
            if k.threshold == base.known_scopes[s].threshold]

        # filter outputted keywords
        namespace.enabled_keywords = base.filter_update(
            namespace.enabled_keywords, enabled_keywords, disabled_keywords)

    if namespace.selected_keywords is not None:
        disabled_keywords, enabled_keywords = namespace.selected_keywords

        errors = (x.__name__ for x in _known_keywords if issubclass(x, base.Error))
        warnings = (x.__name__ for x in _known_keywords if issubclass(x, base.Warning))

        alias_map = {'errors': errors, 'warnings': warnings}
        replace_aliases = lambda x: alias_map.get(x, [x])

        # expand keyword aliases to keyword lists
        disabled_keywords = list(chain.from_iterable(map(replace_aliases, disabled_keywords)))
        enabled_keywords = list(chain.from_iterable(map(replace_aliases, enabled_keywords)))

        # validate selected keywords
        selected_keywords = set(disabled_keywords + enabled_keywords)
        available_keywords = set(x.__name__ for x in _known_keywords)
        unknown_keywords = selected_keywords - available_keywords
        if unknown_keywords:
            parser.error("unknown keyword%s: %s (use 'pkgcheck show --keywords' to show valid keywords)" % (
                _pl(unknown_keywords), ', '.join(map(repr, unknown_keywords))))

        # filter outputted keywords
        namespace.enabled_keywords = base.filter_update(
            namespace.enabled_keywords, enabled_keywords, disabled_keywords)

    namespace.filtered_keywords = set(namespace.enabled_keywords)
    if namespace.filtered_keywords == set(_known_keywords):
        namespace.filtered_keywords = None

    disabled_checks, enabled_checks = ((), ())
    if namespace.selected_checks is not None:
        disabled_checks, enabled_checks = namespace.selected_checks
        # validate selected checks
        selected_checks = set(disabled_checks + enabled_checks)
        available_checks = set(x.__name__ for x in _known_checks)
        unknown_checks = selected_checks - available_checks
        if unknown_checks:
            parser.error("unknown check%s: %s (use 'pkgcheck show --checks' to show valid checks)" % (
                _pl(unknown_checks), ', '.join(map(repr, unknown_checks))))
    elif namespace.filtered_keywords is not None:
        # enable checks based on enabled keyword -> check mapping
        enabled_checks = []
        for check in _known_checks:
            if namespace.filtered_keywords.intersection(check.known_results):
                enabled_checks.append(check.__name__)

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
    if not options.repo_bases:
        err.write(
            'Warning: could not determine repo base for profiles, some checks will not work.')
        err.write()

    if options.guessed_suite:
        if options.default_suite:
            err.write('Tried to guess a suite to use but got multiple matches')
            err.write('and fell back to the default.')
        else:
            err.write('using suite guessed from working directory')

    try:
        reporter = options.reporter(
            out, keywords=options.filtered_keywords, verbosity=options.verbosity)
    except errors.ReporterInitError as e:
        err.write(f'{scan.prog}: failed initializing reporter: {e}')
        return 1

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
        err.write('base dirs: ', ', '.join(options.repo_bases))
        for filterer in options.limiters:
            err.write('limiter: ', filterer)
        debug = logging.debug
    else:
        debug = None

    transforms = list(get_plugins('transform', plugins))
    # XXX this is pretty horrible.
    sinks = list(addon for addon in addons_map.values()
                 if getattr(addon, 'feed_type', False))

    if not sinks:
        err.write(f'{scan.prog}: no matching checks available for current scope')
        return

    raw_sources = []
    for source in feeds.all_sources():
        addons = [addons_map.get(cls, cls(options)) for cls in source.required_addons]
        raw_sources.append(partial(source, options, *addons))

    reporter.start()

    for filterer in options.limiters:
        sources = [source(filterer) for source in raw_sources]
        bad_sinks, pipes = base.plug(sinks, transforms, sources, debug)
        if bad_sinks:
            # We want to report the ones that would work if this was a
            # full repo scan separately from the ones that are
            # actually missing transforms.
            bad_sinks = set(bad_sinks)
            full_scope = [source(packages.AlwaysTrue) for source in raw_sources]
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
        for source, pipe in pipes:
            for result in pipe.start():
                reporter.report(result)
            reporter.start_check(
                list(base.collect_checks_classes(pipe)), filterer)
            for item in source.feed():
                for result in pipe.feed(item):
                    reporter.report(result)
            for result in pipe.finish():
                reporter.report(result)
            reporter.end_check()

    reporter.finish()

    # flush stdout first; if they're directing it all to a file, this makes
    # results not get the final message shoved in midway
    out.stream.flush()
    return 0


replay = subparsers.add_parser(
    'replay',
    description='replay results streams',
    docs="""
        Replay previous results streams from pkgcheck, feeding the results into
        a reporter. Currently only supports replaying streams from
        pickled-based reporters.

        Useful if you need to delay acting on results until it can be done in
        one minimal window (say updating a database), or want to generate
        several different reports without using a config defined multiplex
        reporter.
    """)
replay.add_argument(
    dest='pickle_file', type=argparse.FileType('rb'), help='pickled results file')
replay.add_argument(
    dest='reporter', help='python namespace path reporter to replay it into')
replay.add_argument(
    '--out', default=None, help='redirect reporters output to a file')
@replay.bind_final_check
def _replay_validate_args(parser, namespace):
    func = namespace.config.pkgcheck_reporter_factory.get(namespace.reporter)
    if func is None:
        func = list(base.Whitelist([namespace.reporter]).filter(
            get_plugins('reporter', plugins)))
        if not func:
            available = ', '.join(sorted(
                x.__name__ for x in get_plugins('reporter', plugins)))
            parser.error(
                f"no reporter matches {namespace.reporter!r} "
                f"(available: {available})")
        elif len(func) > 1:
            reporters = tuple(sorted(f"{x.__module__}.{x.__name__}" for x in func))
            parser.error(
                f"reporter {namespace.reporter!r} matched multiple reporters, "
                f"must match one. {reporters!r}")
        func = func[0]
    namespace.reporter = func


def replay_stream(stream_handle, reporter, debug=None):
    headers = []
    last_count = 0
    for count, item in enumerate(pickling.iter_stream(stream_handle)):
        if isinstance(item, base.StreamHeader):
            if debug:
                if headers:
                    debug.write(f"finished processing {count - last_count}"
                                f"results for {headers[-1].criteria}")
                last_count = count
                debug.write(f"encountered new stream header for {item.criteria}")
            if headers:
                reporter.end_check()
            reporter.start_check(item.checks, item.criteria)
            headers.append(item)
            continue
        reporter.report(item)
    if headers:
        reporter.end_check()
        if debug:
            debug.write(f"finished processing {count - last_count}"
                        f"results for {headers[-1].criteria}")


@replay.bind_main_func
def _replay(options, out, err):
    if options.out:
        out = formatters.get_formatter(open(options.out, 'w'))
    debug = None
    if options.debug:
        debug = err
    replay_stream(options.pickle_file, options.reporter(out), debug=debug)
    return 0


def dump_docstring(out, obj, prefix=None):
    if prefix is not None:
        out.first_prefix.append(prefix)
        out.later_prefix.append(prefix)
    try:
        if obj.__doc__ is None:
            out.write("no documentation")
            return

        # Docstrings start with an unindented line. Everything
        # else is consistently indented.
        lines = obj.__doc__.split('\n')
        firstline = lines[0].strip()
        # Some docstrings actually start on the second line.
        if firstline:
            out.write(firstline)
        if len(lines) > 1:
            if firstline:
                out.write()
            for line in textwrap.dedent('\n'.join(lines[1:])).split('\n'):
                if line:
                    out.write(line)
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
    for keyword in _known_keywords:
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
                    out.write()
            finally:
                out.first_prefix.pop()
                out.later_prefix.pop()


@decorate_forced_wrapping()
def display_checks(out, options):
    d = {}
    for x in _known_checks:
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
                    out.write()

                    # output result types that each check can generate
                    if check.known_results:
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
def display_reporters(out, options, config_reporters, plugin_reporters):
    if options.verbosity < 1:
        out.write('\n'.join(sorted(x.__name__ for x in plugin_reporters)), wrap=False)
    else:
        if config_reporters:
            out.write("configured reporters:")
            out.write()
            out.first_prefix.append('  ')
            out.later_prefix.append('  ')
            try:
                # sorting here is random
                for reporter in sorted(config_reporters, key=attrgetter('__name__')):
                    key = options.config.get_section_name(reporter)
                    if not key:
                        continue
                    out.write(out.bold, key)
                    dump_docstring(out, reporter, prefix='  ')
                    out.write()
            finally:
                out.first_prefix.pop()
                out.later_prefix.pop()

        if plugin_reporters:
            if config_reporters:
                out.write()
                out.write("plugin reporters:")
                out.write()
                out.first_prefix.append('  ')
                out.later_prefix.append('  ')
            try:
                for reporter in sorted(plugin_reporters, key=attrgetter('__name__')):
                    out.write(out.bold, out.fg('yellow'), reporter.__name__)
                    dump_docstring(out, reporter, prefix='  ')
                    out.write()
            finally:
                if config_reporters:
                    out.first_prefix.pop()
                    out.later_prefix.pop()

        if not plugin_reporters and not config_reporters:
            out.write(
                out.fg("red"), "Warning", out.fg(""),
                " no reporters detected; pkgcheck won't "
                "run correctly without a reporter to use!")
            out.write()


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
        display_reporters(
            out, options,
            list(options.config.pkgcheck_reporter_factory.values()),
            list(get_plugins('reporter', plugins)))

    return 0
