# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# Copyright: 2006 Marien Zwart <marienz@gentoo.org>
# License: GPL2


"""Commandline frontend (for use with L{pkgcore.util.commandline.main}."""


from pkgcore.util import commandline, parserestrict, lists, demandload
from pkgcore.util.compatibility import any
from pkgcore.config import ConfigHint
from pkgcore.plugin import get_plugins

from pkgcore_checks import plugins, base, __version__, feeds

demandload.demandload(globals(), "optparse textwrap re os "
    "pkgcore.util:osutils "
    "pkgcore.restrictions:packages "
    "pkgcore.restrictions.values:StrExactMatch "
    "pkgcore.repository:multiplex "
    "pkgcore.ebuild:repository "
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


class _CheckSet(object):

    """Run only listed checks."""

    # No config hint here since this one is abstract.

    def __init__(self, patterns):
        self.patterns = list(convert_check_filter(pat) for pat in patterns)

class Whitelist(_CheckSet):

    pkgcore_config_type = ConfigHint(
        {'patterns': 'list'}, typename='pcheck_checkset')

    def filter(self, checks):
        return list(
            c for c in checks
            if any(f('%s.%s' % (c.__module__, c.__name__))
                   for f in self.patterns))

class Blacklist(_CheckSet):

    pkgcore_config_type = ConfigHint(
        {'patterns': 'list'}, typename='pcheck_checkset')

    def filter(self, checks):
        return list(
            c for c in checks
            if not any(f('%s.%s' % (c.__module__, c.__name__))
                       for f in self.patterns))


class Suite(object):

    pkgcore_config_type = ConfigHint({
            'target_repo': 'ref:repo', 'src_repo': 'ref:repo',
            'checkset': 'ref:pcheck_checkset'}, typename='pcheck_suite')

    def __init__(self, target_repo, checkset=None, src_repo=None):
        self.target_repo = target_repo
        self.checkset = checkset
        self.src_repo = src_repo


class OptionParser(commandline.OptionParser):

    """Option parser that is automagically extended by the checks.

    Some comments on the resulting values object:

    - target_repo is passed in as first argument and used as source for
      packages to check.
    - src_repo is specified with -r or defaults to target_repo. It is used
      to get the profiles directory and other non-package repository data.
    - repo_base is the path to src_repo (or None).
    - search_repo is a multiplex of target_repo and src_repo if they are
      different or just target_repo if they are the same. This is used for
      things like visibility checks (it is passed to the checkers in "start").
    """

    def __init__(self, **kwargs):
        commandline.OptionParser.__init__(
            self, version='pkgcore-checks %s' % (__version__,),
            description="pkgcore based ebuild QA checks",
            usage="usage: %prog [options] [atom1...atom2]",
            **kwargs)

        # These are all set in check_values based on other options, so have
        # no default set through add_option.
        self.set_default('repo_base', None)
        self.set_default('guessed_target_repo', False)
        self.set_default('guessed_suite', False)
        self.set_default('default_suite', False)

        group = self.add_option_group('Check selection')
        group.add_option(
            "-c", action="append", type="string", dest="checks_to_run",
            help="limit checks to those matching this regex, or package/class "
            "matching; may be specified multiple times")
        group.add_option(
            "--disable", action="append", type="string",
            dest="checks_to_disable", help="specific checks to disable: "
            "may be specified multiple times")
        group.add_option(
            '--checkset', action='callback', type='string',
            callback=commandline.config_callback,
            callback_args=('pcheck_checkset', 'checkset'),
            help='Pick a preconfigured set of checks to run.')

        self.add_option(
            '--repo', '-r', action='callback', type='string',
            callback=repo_callback, dest='target_repo',
            help='Set the target repo')
        self.add_option(
            '--suite', '-s', action='callback', type='string',
            callback=commandline.config_callback,
            callback_args=('pcheck_suite', 'suite'),
            help='Specify the configuration suite to use')
        self.add_option(
            "--list-checks", action="store_true", default=False,
            dest="list_checks",
            help="print what checks are available to run and exit")
        self.add_option(
            '--reporter', action='callback', type='string',
            callback=commandline.config_callback,
            callback_args=('pcheck_reporter_factory', 'reporter'),
            help="Use a non-default reporter (defined in pkgcore's config).")

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
        values.checks = sorted(get_plugins('check', plugins))
        if values.list_checks:
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
                for name, suite in values.config.pcheck_suite.iteritems():
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
                    suite for suite in values.config.pcheck_suite.itervalues()
                    if suite.target_repo is values.target_repo)
                if len(candidates) == 1:
                    values.guessed_suite = True
                    values.suite = candidates[0]
            if values.suite is None:
                # If we have multiple candidates or no candidates we
                # fall back to the default suite.
                values.suite = values.config.get_default('pcheck_suite')
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
            if values.target_repo is None and args:
                values.checkset = values.suite.target_repo
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
                'pcheck_reporter_factory')
            if values.reporter is None:
                values.reporter = base.FancyReporter

        if values.src_repo is None:
            values.src_repo = values.target_repo
            values.search_repo = values.target_repo
        else:
            values.search_repo = multiplex.tree(values.target_repo,
                                                values.src_repo)

        if isinstance(values.src_repo, repository.UnconfiguredTree):
            values.repo_base = osutils.abspath(values.src_repo.base)

        if args:
            values.limiters = lists.stable_unique(map(
                    parserestrict.parse_match, args))
        else:
            repo_base = getattr(values.target_repo, 'base', None)
            if not repo_base:
                self.error(
                    'Either specify a target repo that is not multi-tree or '
                    'one or more extended atoms to scan '
                    '("*" for the entire repo).')
            cwd = osutils.abspath(os.getcwd())
            repo_base = osutils.abspath(repo_base)
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
            values.checkset = values.config.get_default('pcheck_checkset')
        if values.checkset is not None:
            values.checks = list(values.checkset.filter(values.checks))

        if values.checks_to_run:
            whitelist = Whitelist(values.checks_to_run)
            values.checks = list(whitelist.filter(values.checks))

        if values.checks_to_disable:
            blacklist = Blacklist(values.checks_to_disable)
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


def convert_check_filter(tok):
    """Convert an input string into a filter function.

    The filter function accepts a qualified python identifier string
    and returns a bool.

    The input can be a regexp or a simple string. A simple string must
    match a component of the qualified name exactly. A regexp is
    matched against the entire qualified name.

    Matches are case-insensitive.

    Examples::

      convert_check_filter('foo')('a.foo.b') == True
      convert_check_filter('foo')('a.foobar') == False
      convert_check_filter('foo.*')('a.foobar') == False
      convert_check_filter('foo.*')('foobar') == True
    """
    tok = tok.lower()
    if '+' in tok or '*' in tok:
        return re.compile(tok, re.I).match
    else:
        def func(name):
            return tok in name.lower().split('.')
        return func


def display_checks(out, checks):
    for x in checks:
        out.write(out.bold, "%s.%s" % (x.__module__, x.__name__))
        out.first_prefix.append('  ')
        out.later_prefix.append('  ')
        oldwrap = out.wrap
        out.wrap = True
        if x.__doc__ is not None:
            # Docstrings start with an unindented line. Everything
            # else is consistently indented.
            lines = x.__doc__.split('\n')
            firstline = lines[0].strip()
            # Some docstrings actually start on the second line.
            if firstline:
                out.write(firstline)
            if len(lines) > 1:
                for line in textwrap.dedent('\n'.join(lines[1:])).split('\n'):
                    if line:
                        out.write(line)
        else:
            out.write(out.fg('red'), "No Documentation")
        out.first_prefix.pop()
        out.later_prefix.pop()
        out.wrap = oldwrap
        out.write()


def main(options, out, err):
    """Do stuff."""

    if options.list_checks:
        display_checks(out, options.checks)
        return 0

    if options.repo_base is None:
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
    except base.ReporterInitError, e:
        err.write(err.fg('red'), err.bold, '!!! ', err.reset,
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

    transforms = list(transform(options)
                      for transform in get_plugins('transform', plugins))
    sinks = list(addon for addon in addons_map.itervalues()
                 if getattr(addon, 'feed_type', False))

    reporter.start()
    if options.debug:
        import logging
        debug = logging.warning
    else:
        debug = None
    for filterer in options.limiters:
        sources = [feeds.RestrictedRepoSource(options.target_repo, filterer)]
        out_of_scope, unreachables, good_sinks, pipes = base.plug(
            sinks, transforms, sources, reporter, debug)
        # TODO the reporting of out of scope/unreachable needs further thought.

        # The trick is we want to distinguish between things that are
        # simply out of scope and things that are unreachable because
        # the set of transforms is really incomplete, and this does
        # not quite match the two things plug returns. Specifically
        # the checks that want a non-version feed are relying on their
        # transform being out of scope, and that triggers an
        # "unreachable" from the plugger. Need to figure out if that
        # can be fixed by making the plugger smarter about error
        # reporting or if those checks should grow a more specific
        # scope attr.
        for sink in out_of_scope + unreachables:
            # Skip (addon) sinks that are not checks.
            if sink.__class__ in options.checks:
                out.write(
                    out.fg('yellow'), ' * ', out.reset,
                    '%s is out of scope or unreachable, skipped.' % (
                        sink.__class__.__name__,))
        if not good_sinks or not pipes:
            out.write(out.fg('red'), ' * ', out.reset, 'No checks!')
        else:
            out.write('Running %s tests' % (len(good_sinks),))
            for pipe in pipes:
                for thing in pipe:
                    pass
    reporter.finish()
    # flush stdout first; if they're directing it all to a file, this makes
    # results not get the final message shoved in midway
    out.stream.flush()
    return 0
