# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# Copyright: 2006 Marien Zwart <marienz@gentoo.org>
# License: BSD/GPL2

"""pkgcore-based QA utility"""

from __future__ import absolute_import

import argparse

from pkgcore.plugin import get_plugins, get_plugin
from pkgcore.util import commandline, parserestrict
from snakeoil.demandload import demandload
from snakeoil.formatters import decorate_forced_wrapping
from snakeoil.sequences import unstable_unique

from pkgcheck import plugins, base, feeds

demandload(
    'logging',
    'os',
    'textwrap',
    'pkgcore.ebuild:repository',
    'pkgcore.restrictions:packages',
    'pkgcore.restrictions.values:StrExactMatch',
    'pkgcore.repository:multiplex',
    'snakeoil.osutils:abspath',
    'pkgcheck:errors',
)

argparser = commandline.ArgumentParser(
    domain=False, color=False, description=__doc__)
# These are all set based on other options, so have no default setting.
argparser.set_defaults(repo_bases=[])
argparser.set_defaults(guessed_target_repo=False)
argparser.set_defaults(guessed_suite=False)
argparser.set_defaults(default_suite=False)
argparser.add_argument(
    'targets', metavar='TARGET', nargs='*', help='optional target atom(s)')

main_options = argparser.add_argument_group('main options')
main_options.add_argument(
    '-r', '--repo', metavar='REPO', dest='target_repo',
    action=commandline.StoreRepoObject,
    help='repo to pull packages from')
main_options.add_argument(
    '-s', '--suite', action=commandline.StoreConfigObject,
    config_type='pkgcheck_suite',
    help='Specify the configuration suite to use')
main_options.add_argument(
    '--reporter', action='store', default=None,
    help="use a non-default reporter (defined in pkgcore's config)")
main_options.add_argument(
    '-o', '--overlayed-repo', metavar='REPO',
    action=commandline.StoreRepoObject, dest='src_repo',
    help='if the target repo is an overlay, specify the '
         'repository name to pull profiles/license from')
list_options = main_options.add_mutually_exclusive_group()
list_options.add_argument(
    '--list-checks', action='store_true', default=False,
    help='show available checks and exit')
list_options.add_argument(
    '--list-reporters', action='store_true', default=False,
    help='show available reporters and exit')

check_options = argparser.add_argument_group('check selection')
check_options.add_argument(
    '-c', '--check', action='append', dest='checks_to_run',
    help='limit checks to regex or package/class matching')
check_options.add_argument(
    '-d', '--disable', action='append', dest='checks_to_disable',
    help='specific checks to disable')
check_options.add_argument(
    '--checkset', action=commandline.StoreConfigObject,
    config_type='pkgcheck_checkset',
    help='preconfigured set of checks to run')


all_addons = set()
def add_addon(addon):
    if addon not in all_addons:
        all_addons.add(addon)
        for dep in addon.required_addons:
            add_addon(dep)

argparser.plugin = argparser.add_argument_group('plugin options')
for check in get_plugins('check', plugins):
    add_addon(check)
for addon in all_addons:
    addon.mangle_argparser(argparser)


@argparser.bind_final_check
def check_args(parser, namespace):
    # XXX hack...
    namespace.checks = sorted(unstable_unique(
        get_plugins('check', plugins)),
        key=lambda x: x.__name__)

    if namespace.list_checks or namespace.list_reporters:
        # no need to check any other args
        return

    cwd = None
    if namespace.suite is None:
        # No suite explicitly specified. Use the repo to guess the suite.
        if namespace.target_repo is None:
            # Not specified either. Try to find a repo our cwd is in.
            cwd = os.getcwd()
            # The use of a dict here is a hack to deal with one
            # repo having multiple names in the configuration.
            candidates = {}
            for name, suite in namespace.config.pkgcheck_suite.iteritems():
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
                suite for suite in namespace.config.pkgcheck_suite.itervalues()
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
        if namespace.src_repo is None:
            namespace.src_repo = namespace.suite.src_repo
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
                if cwd is None:
                    cwd = os.getcwd()
                repo_base = getattr(namespace.suite.target_repo, 'location', None)
                if repo_base is not None and cwd.startswith(repo_base):
                    namespace.target_repo = namespace.suite.target_repo
    if namespace.target_repo is None:
        # We have no target repo (not explicitly passed, not from
        # a suite, not from an earlier guess at the target_repo).
        # Try to guess one from cwd:
        if cwd is None:
            cwd = os.getcwd()
        candidates = {}
        for name, repo in namespace.config.repo.iteritems():
            repo_base = getattr(repo, 'location', None)
            if repo_base is not None and cwd in repo:
                candidates[repo] = name
        if not candidates:
            parser.error(
                'No target repo specified on commandline or suite and '
                'current directory is not inside a known repo.')
        elif len(candidates) > 1:
            parser.error(
                'Found multiple matches when guessing repo based on '
                'current directory (%s). Specify a repo on the '
                'commandline or suite or remove some repos from your '
                'configuration.' % (
                    ', '.join(str(repo) for repo in candidates),))
        namespace.target_repo = tuple(candidates)[0]

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
                parser.error(
                    "no reporter matches %r\n"
                    "please see --list-reporters for a list of "
                    "valid reporters" % namespace.reporter)
            elif len(func) > 1:
                parser.error(
                    "--reporter %r matched multiple reporters, "
                    "must match one. %r" % (
                        namespace.reporter,
                        tuple(sorted("%s.%s" % (x.__module__, x.__name__) for x in func))
                    )
                )
            func = func[0]
        namespace.reporter = func

    # search_repo is a multiplex of target_repo and src_repo if they are
    # different or just target_repo if they are the same. This is used for
    # things like visibility checks (it is passed to the checkers in "start").
    if namespace.src_repo is None:
        namespace.src_repo = namespace.target_repo
        namespace.search_repo = namespace.target_repo
    else:
        namespace.search_repo = multiplex.tree(namespace.target_repo, namespace.src_repo)

    # TODO improve this to deal with a multiplex repo.
    for repo in set((namespace.src_repo, namespace.target_repo)):
        if isinstance(repo, repository.UnconfiguredTree):
            namespace.repo_bases.append(abspath(repo.location))

    if namespace.targets:
        limiters = []
        repo = namespace.target_repo
        for target in namespace.targets:
            if os.path.exists(target):
                try:
                    limiters.append(repo.path_restrict(target))
                except ValueError as e:
                    parser.error(e)
            else:
                try:
                    limiters.append(parserestrict.parse_match(target))
                except ValueError as e:
                    parser.error(e)
        namespace.limiters = limiters
    else:
        repo_base = getattr(namespace.target_repo, 'location', None)
        if not repo_base:
            parser.error(
                'Either specify a target repo that is not multi-tree or '
                'one or more extended atoms to scan '
                '("*" for the entire repo).')
        cwd = abspath(os.getcwd())
        repo_base = abspath(repo_base)
        if not cwd.startswith(repo_base):
            parser.error(
                'Working dir (%s) is not inside target repo (%s). Fix '
                'that or specify one or more extended atoms to scan.' % (
                    cwd, repo_base))
        bits = list(p for p in cwd[len(repo_base):].split(os.sep) if p)
        if not bits:
            namespace.limiters = [packages.AlwaysTrue]
        elif len(bits) == 1:
            namespace.limiters = [packages.PackageRestriction(
                'category', StrExactMatch(bits[0]))]
        else:
            namespace.limiters = [packages.AndRestriction(
                packages.PackageRestriction(
                    'category', StrExactMatch(bits[0])),
                packages.PackageRestriction(
                    'package', StrExactMatch(bits[1])))]

    if namespace.checkset is None:
        namespace.checkset = namespace.config.get_default('pkgcheck_checkset')
    if namespace.checkset is not None:
        namespace.checks = list(namespace.checkset.filter(namespace.checks))

    if namespace.checks_to_run:
        whitelist = base.Whitelist(namespace.checks_to_run)
        namespace.checks = list(whitelist.filter(namespace.checks))

    if namespace.checks_to_disable:
        blacklist = base.Blacklist(namespace.checks_to_disable)
        namespace.checks = list(blacklist.filter(namespace.checks))

    if not namespace.checks:
        parser.error('No active checks')

    namespace.addons = set()

    def add_addon(addon):
        if addon not in namespace.addons:
            namespace.addons.add(addon)
            for dep in addon.required_addons:
                add_addon(dep)
    for check in namespace.checks:
        add_addon(check)
    try:
        for addon in namespace.addons:
            addon.check_args(parser, namespace)
    except argparse.ArgumentError as e:
        if namespace.debug:
            raise
        parser.error(str(e))


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
            for line in textwrap.dedent('\n'.join(lines[1:])).split('\n'):
                if line:
                    out.write(line)
    finally:
        if prefix is not None:
            out.first_prefix.pop()
            out.later_prefix.pop()


@decorate_forced_wrapping()
def display_checks(out, checks):
    d = {}
    for x in checks:
        d.setdefault(x.__module__, []).append(x)

    if not d:
        out.write(out.fg('red'), "No Documentation")
        out.write()
        return

    for module_name in sorted(d):
        out.write(out.bold, "%s:" % module_name)
        l = d[module_name]
        l.sort(key=lambda x: x.__name__)

        try:
            out.first_prefix.append('  ')
            out.later_prefix.append('  ')
            for check in l:
                out.write(out.fg('yellow'), check.__name__, out.reset, ':')
                dump_docstring(out, check, prefix='  ')
            out.write()
        finally:
            out.first_prefix.pop()
            out.later_prefix.pop()


@decorate_forced_wrapping()
def display_reporters(out, config, config_reporters, plugin_reporters):
    out.write("known reporters:")
    out.write()
    if config_reporters:
        out.write("configured reporters:")
        out.first_prefix.append(' ')
        out.later_prefix.append(' ')
        try:
            # sorting here is random
            for reporter in sorted(config_reporters, key=lambda x: x.__name__):
                key = config.get_section_name(reporter)
                if not key:
                    continue
                out.write(out.bold, key)
                dump_docstring(out, reporter, prefix=' ')
                out.write()
        finally:
            out.first_prefix.pop()
            out.later_prefix.pop()

    if plugin_reporters:
        if config_reporters:
            out.write()
        out.write("plugin reporters:")
        out.first_prefix.append(' ')
        out.later_prefix.append(' ')
        try:
            for reporter in sorted(plugin_reporters, key=lambda x: x.__name__):
                out.write(out.bold, reporter.__name__)
                dump_docstring(out, reporter, prefix=' ')
                out.write()
        finally:
            out.first_prefix.pop()
            out.later_prefix.pop()

    if not plugin_reporters and not config_reporters:
        out.write(
            out.fg("red"), "Warning", out.fg(""),
            " no reporters detected; pkgcheck won't "
            "run correctly without a reporter to use!")
        out.write()


@argparser.bind_main_func
def main(options, out, err):
    """Do stuff."""

    if options.list_checks:
        display_checks(out, options.checks)
        return 0

    if options.list_reporters:
        display_reporters(
            out, options.config,
            options.config.pkgcheck_reporter_factory.values(),
            list(get_plugins('reporter', plugins)))
        return 0

    if not options.repo_bases:
        err.write(
            'Warning: could not determine repository base for profiles. '
            'Some checks will not work. Either specify a plain target repo '
            '(not combined trees) or specify a master repo '
            'with --overlayed-repo.', wrap=True)
        err.write()

    if options.guessed_suite:
        if options.default_suite:
            err.write('Tried to guess a suite to use but got multiple matches')
            err.write('and fell back to the default.')
        else:
            err.write('using suite guessed from working directory')

    if options.guessed_target_repo:
        err.write('using repository guessed from working directory')

    try:
        reporter = options.reporter(out)
    except errors.ReporterInitError as e:
        err.write(
            err.fg('red'), err.bold, '!!! ', err.reset,
            'Error initializing reporter: ', e)
        return 1

    addons_map = {}

    def init_addon(klass):
        res = addons_map.get(klass)
        if res is not None:
            return res
        deps = list(init_addon(dep) for dep in klass.required_addons)
        try:
            res = addons_map[klass] = klass(options, *deps)
        except KeyboardInterrupt:
            raise
        except Exception:
            err.write('instantiating %s' % (klass,))
            raise
        return res

    for addon in options.addons:
        # Ignore the return value, we just need to populate addons_map.
        init_addon(addon)

    if options.debug:
        err.write('target repo: ', repr(options.target_repo))
        err.write('source repo: ', repr(options.src_repo))
        err.write('base dirs: ', repr(options.repo_bases))
        for filterer in options.limiters:
            err.write('limiter: ', repr(filterer))
        debug = logging.debug
    else:
        debug = None

    transforms = list(get_plugins('transform', plugins))
    # XXX this is pretty horrible.
    sinks = list(addon for addon in addons_map.itervalues()
                 if getattr(addon, 'feed_type', False))

    reporter.start()

    for filterer in options.limiters:
        sources = [feeds.RestrictedRepoSource(options.target_repo, filterer)]
        bad_sinks, pipes = base.plug(sinks, transforms, sources, debug)
        if bad_sinks:
            # We want to report the ones that would work if this was a
            # full repo scan separately from the ones that are
            # actually missing transforms.
            bad_sinks = set(bad_sinks)
            full_scope = feeds.RestrictedRepoSource(
                options.target_repo, packages.AlwaysTrue)
            really_bad, ignored = base.plug(sinks, transforms, [full_scope])
            really_bad = set(really_bad)
            assert bad_sinks >= really_bad, \
                '%r unreachable with no limiters but reachable with?' % (
                    really_bad - bad_sinks,)
            out_of_scope = bad_sinks - really_bad
            for sink in really_bad:
                err.error(
                    'sink %s could not be connected (missing transforms?)' % (
                        sink,))
            for sink in bad_sinks - really_bad:
                err.warn('not running %s (not a full repo scan)' % (
                    sink.__class__.__name__,))
        if not pipes:
            out.write(out.fg('red'), ' * ', out.reset, 'No checks!')
        else:
            if options.debug:
                err.write('Running %i tests' % (len(sinks) - len(bad_sinks),))
            for source, pipe in pipes:
                pipe.start()
                reporter.start_check(
                    list(base.collect_checks_classes(pipe)), filterer)
                for thing in source.feed():
                    pipe.feed(thing, reporter)
                pipe.finish(reporter)
                reporter.end_check()

    reporter.finish()

    # flush stdout first; if they're directing it all to a file, this makes
    # results not get the final message shoved in midway
    out.stream.flush()
    return 0
