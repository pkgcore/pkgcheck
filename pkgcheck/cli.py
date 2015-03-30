# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# Copyright: 2006 Marien Zwart <marienz@gentoo.org>
# License: BSD/GPL2

"""pkgcore-based QA utility"""

from pkgcore.util import commandline, parserestrict
from pkgcore.plugin import get_plugins, get_plugin
from snakeoil import lists
from snakeoil.formatters import decorate_forced_wrapping

from pkgcheck import plugins, base, __version__, feeds

from snakeoil.demandload import demandload
demandload(
    'logging',
    'optparse',
    'os',
    'textwrap',
    'pkgcore.ebuild:repository',
    'pkgcore.restrictions:packages',
    'pkgcore.restrictions.values:StrExactMatch',
    'pkgcore.repository:multiplex',
    'snakeoil.osutils:abspath',
    'pkgcheck:errors',
)


def repo_callback(option, opt_str, value, parser):
    try:
        repo = parser.values.config.repo[value]
    except KeyError:
        raise optparse.OptionValueError(
            'repo %r is not a known repo (known repos: %s)' % (
                value, ', '.join(repr(n) for n in parser.values.config.repo)))
    if not isinstance(repo, repository.UnconfiguredTree):
        raise optparse.OptionValueError(
            'repo %r is not a pkgcore.ebuild.repository.UnconfiguredTree '
            'instance; must specify a raw ebuild repo, not type %r: %r' % (
                value, repo.__class__, repo))
    setattr(parser.values, option.dest, repo)


class OptionParser(commandline.OptionParser):

    """Option parser that is automagically extended by the checks.

    Some comments on the resulting values object:

    - target_repo is passed in as first argument and used as source for
      packages to check.
    - src_repo is specified with -r or defaults to target_repo. It is used
      to get the profiles directory and other non-package repository data.
    - repo_bases are the path(s) to selected repo(s).
    - search_repo is a multiplex of target_repo and src_repo if they are
      different or just target_repo if they are the same. This is used for
      things like visibility checks (it is passed to the checkers in "start").
    """

    def __init__(self, **kwargs):
        commandline.OptionParser.__init__(
            self, version='pkgcheck %s' % (__version__,),
            description="pkgcore based ebuild QA checks",
            usage="usage: %prog [options] [atom1...atom2]",
            **kwargs)

        # These are all set in check_values based on other options, so have
        # no default set through add_option.
        self.set_default('repo_bases', [])
        self.set_default('guessed_target_repo', False)
        self.set_default('guessed_suite', False)
        self.set_default('default_suite', False)

        group = self.add_option_group('Check selection')
        group.add_option(
            "-c", action="append", type="string", dest="checks_to_run",
            help="limit checks to those matching this regex, or package/class "
            "matching; may be specified multiple times")
        group.set_conflict_handler("resolve")
        group.add_option(
            "-d", "--disable", action="append", type="string",
            dest="checks_to_disable", help="specific checks to disable: "
            "may be specified multiple times")
        group.set_conflict_handler("error")
        group.add_option(
            '--checkset', action='callback', type='string',
            callback=commandline.config_callback,
            callback_args=('pkgcheck_checkset', 'checkset'),
            help='Pick a preconfigured set of checks to run.')

        self.add_option(
            '--repo', '-r', action='callback', type='string',
            callback=repo_callback, dest='target_repo',
            help='Set the target repo')
        self.add_option(
            '--suite', '-s', action='callback', type='string',
            callback=commandline.config_callback,
            callback_args=('pkgcheck_suite', 'suite'),
            help='Specify the configuration suite to use')
        self.add_option(
            "--list-checks", action="store_true", default=False,
            help="print what checks are available to run and exit")
        self.add_option(
            '--reporter', type='string', action='store', default=None,
            help="Use a non-default reporter (defined in pkgcore's config).")
        self.add_option(
            '--list-reporters', action='store_true', default=False,
            help="print known reporters")

        overlay = self.add_option_group('Overlay')
        overlay.add_option(
            '--overlayed-repo', '-o', action='callback', type='string',
            callback=repo_callback, dest='src_repo',
            help="if the target repository is an overlay, specify the "
            "repository name to pull profiles/license from")

        all_addons = set()

        def add_addon(addon):
            if addon not in all_addons:
                all_addons.add(addon)
                for dep in addon.required_addons:
                    add_addon(dep)
        for check in get_plugins('check', plugins):
            add_addon(check)
        for addon in all_addons:
            addon.mangle_option_parser(self)

    def check_values(self, values, args):
        values, args = commandline.OptionParser.check_values(
            self, values, args)
        # XXX hack...
        values.checks = sorted(lists.unstable_unique(
            get_plugins('check', plugins)),
            key=lambda x: x.__name__)
        if values.list_checks or values.list_reporters:
            if values.list_reporters == values.list_checks:
                raise optparse.OptionValueError(
                    "--list-checks and --list-reporters are mutually exclusive")
            return values, ()
        cwd = None
        if values.suite is None:
            # No suite explicitly specified. Use the repo to guess the suite.
            if values.target_repo is None:
                # Not specified either. Try to find a repo our cwd is in.
                cwd = os.getcwd()
                # The use of a dict here is a hack to deal with one
                # repo having multiple names in the configuration.
                candidates = {}
                for name, suite in values.config.pkgcheck_suite.iteritems():
                    repo = suite.target_repo
                    if repo is None:
                        continue
                    repo_base = getattr(repo, 'base', None)
                    if repo_base is not None and cwd.startswith(repo_base):
                        candidates[repo] = name
                if len(candidates) == 1:
                    values.guessed_suite = True
                    values.target_repo = tuple(candidates)[0]
            if values.target_repo is not None:
                # We have a repo, now find a suite matching it.
                candidates = list(
                    suite for suite in values.config.pkgcheck_suite.itervalues()
                    if suite.target_repo is values.target_repo)
                if len(candidates) == 1:
                    values.guessed_suite = True
                    values.suite = candidates[0]
            if values.suite is None:
                # If we have multiple candidates or no candidates we
                # fall back to the default suite.
                values.suite = values.config.get_default('pkgcheck_suite')
                values.default_suite = values.suite is not None
        if values.suite is not None:
            # We have a suite. Lift defaults from it for values that
            # were not set explicitly:
            if values.checkset is None:
                values.checkset = values.suite.checkset
            if values.src_repo is None:
                values.src_repo = values.suite.src_repo
            # If we were called with no atoms we want to force
            # cwd-based detection.
            if values.target_repo is None:
                if args:
                    values.target_repo = values.suite.target_repo
                elif values.suite.target_repo is not None:
                    # No atoms were passed in, so we want to guess
                    # what to scan based on cwd below. That only makes
                    # sense if we are inside the target repo. We still
                    # want to pick the suite's target repo if we are
                    # inside it, in case there is more than one repo
                    # definition with a base that contains our dir.
                    if cwd is None:
                        cwd = os.getcwd()
                    repo_base = getattr(values.suite.target_repo, 'base', None)
                    if repo_base is not None and cwd.startswith(repo_base):
                        values.target_repo = values.suite.target_repo
        if values.target_repo is None:
            # We have no target repo (not explicitly passed, not from
            # a suite, not from an earlier guess at the target_repo).
            # Try to guess one from cwd:
            if cwd is None:
                cwd = os.getcwd()
            candidates = {}
            for name, repo in values.config.repo.iteritems():
                repo_base = getattr(repo, 'base', None)
                if repo_base is not None and cwd.startswith(repo_base):
                    candidates[repo] = name
            if not candidates:
                self.error(
                    'No target repo specified on commandline or suite and '
                    'current directory is not inside a known repo.')
            elif len(candidates) > 1:
                self.error(
                    'Found multiple matches when guessing repo based on '
                    'current directory (%s). Specify a repo on the '
                    'commandline or suite or remove some repos from your '
                    'configuration.' % (
                        ', '.join(str(repo) for repo in candidates),))
            values.target_repo = tuple(candidates)[0]

        if values.reporter is None:
            values.reporter = values.config.get_default(
                'pkgcheck_reporter_factory')
            if values.reporter is None:
                values.reporter = get_plugin('reporter', plugins)
            if values.reporter is None:
                self.error(
                    'no config defined reporter found, nor any default '
                    'plugin based reporters')
        else:
            func = values.config.pkgcheck_reporter_factory.get(values.reporter)
            if func is None:
                func = list(base.Whitelist([values.reporter]).filter(
                    get_plugins('reporter', plugins)))
                if not func:
                    self.error(
                        "no reporter matches %r\n"
                        "please see --list-reporter for a list of "
                        "valid reporters" % values.reporter)
                elif len(func) > 1:
                    self.error(
                        "--reporter %r matched multiple reporters, "
                        "must match one. %r" % (
                            values.reporter,
                            tuple(sorted("%s.%s" % (x.__module__, x.__name__)
                                         for x in func))
                        )
                    )
                func = func[0]
            values.reporter = func
        if values.src_repo is None:
            values.src_repo = values.target_repo
            values.search_repo = values.target_repo
        else:
            values.search_repo = multiplex.tree(values.target_repo,
                                                values.src_repo)

        # TODO improve this to deal with a multiplex repo.
        for repo in set((values.src_repo, values.target_repo)):
            if isinstance(repo, repository.UnconfiguredTree):
                values.repo_bases.append(abspath(repo.base))

        if args:
            values.limiters = lists.stable_unique(
                map(parserestrict.parse_match, args))
        else:
            repo_base = getattr(values.target_repo, 'base', None)
            if not repo_base:
                self.error(
                    'Either specify a target repo that is not multi-tree or '
                    'one or more extended atoms to scan '
                    '("*" for the entire repo).')
            cwd = abspath(os.getcwd())
            repo_base = abspath(repo_base)
            if not cwd.startswith(repo_base):
                self.error(
                    'Working dir (%s) is not inside target repo (%s). Fix '
                    'that or specify one or more extended atoms to scan.' % (
                        cwd, repo_base))
            bits = list(p for p in cwd[len(repo_base):].split(os.sep) if p)
            if not bits:
                values.limiters = [packages.AlwaysTrue]
            elif len(bits) == 1:
                values.limiters = [packages.PackageRestriction(
                    'category', StrExactMatch(bits[0]))]
            else:
                values.limiters = [packages.AndRestriction(
                    packages.PackageRestriction(
                        'category', StrExactMatch(bits[0])),
                    packages.PackageRestriction(
                        'package', StrExactMatch(bits[1])))]

        if values.checkset is None:
            values.checkset = values.config.get_default('pkgcheck_checkset')
        if values.checkset is not None:
            values.checks = list(values.checkset.filter(values.checks))

        if values.checks_to_run:
            whitelist = base.Whitelist(values.checks_to_run)
            values.checks = list(whitelist.filter(values.checks))

        if values.checks_to_disable:
            blacklist = base.Blacklist(values.checks_to_disable)
            values.checks = list(blacklist.filter(values.checks))

        if not values.checks:
            self.error('No active checks')

        values.addons = set()

        def add_addon(addon):
            if addon not in values.addons:
                values.addons.add(addon)
                for dep in addon.required_addons:
                    add_addon(dep)
        for check in values.checks:
            add_addon(check)
        try:
            for addon in values.addons:
                addon.check_values(values)
        except optparse.OptionValueError, e:
            if values.debug:
                raise
            self.error(str(e))

        return values, ()


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
                out.write("%s:" % check.__name__)
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
            '(not combined trees) or specify a PORTDIR repo '
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
    except errors.ReporterInitError, e:
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
