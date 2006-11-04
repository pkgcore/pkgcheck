# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# Copyright: 2006 Marien Zwart <marienz@gentoo.org>
# License: GPL2


"""Commandline frontend (for use with L{pkgcore.util.commandline.main}."""


import optparse

from pkgcore.util import commandline, parserestrict, lists, demandload
from pkgcore.util.compatibility import any
from pkgcore.restrictions import packages
from pkgcore.plugin import get_plugins

from pkgcore_checks import plugins, base, __version__, feeds

demandload.demandload(globals(), "logging optparse textwrap re "
    "pkgcore.util:osutils "
    "pkgcore.repository:multiplex "
    "pkgcore.ebuild:repository "
    )


def metadata_src_callback(option, opt_str, value, parser):
    try:
        repo = parser.values.src_repo = parser.values.config.repo[value]
    except KeyError:
        raise optparse.OptionValueError(
            "overlayed repo %r is not a known repo" % (value,))
    if not isinstance(repo, repository.UnconfiguredTree):
        raise optparse.OptionValueError(
            'overlayed-repo %r is not a '
            'pkgcore.ebuild.repository.UnconfiguredTree instance; '
            'must specify a raw ebuild repo, not type %r: %r' % (
                value, repo.__class__, repo))


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
            usage="usage: %prog repository [options] [atom1...atom2]",
            **kwargs)

        self.set_default('repo_base', None)
        self.set_default('src_repo', None)

        self.add_option(
            "-c", action="append", type="string", dest="checks_to_run",
            help="limit checks to those matching this regex, or package/class "
            "matching; may be specified multiple times")
        self.add_option(
            "--disable", action="append", type="string",
            dest="checks_to_disable", help="specific checks to disable: "
            "may be specified multiple times")
        self.add_option(
            "--list-checks", action="store_true", default=False,
            dest="list_checks",
            help="print what checks are available to run and exit")
        self.add_option(
            '--reporter', action='store',
            help="Use a non-default reporter (defined in pkgcore's config).")

        overlay = self.add_option_group('Overlay')
        overlay.add_option(
            "-r", "--overlayed-repo", action='callback', type='string',
            callback=metadata_src_callback,
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

        if not args:
            self.error('repository name was not specified')

        repo_name = args.pop(0)
        try:
            values.target_repo = values.config.repo[repo_name]
        except KeyError:
            try:
                values.target_repo = values.config.repo[
                    osutils.normpath(repo_name)]
            except KeyError:
                self.error('repo %r is not a valid reponame (known repos: %s)'
                           % (repo_name, ', '.join(repr(x) for x in
                                                   values.config.repo)))

        if values.reporter is None:
            values.reporter = values.config.get_default(
                'pcheck_reporter_factory')
            if values.reporter is None:
                values.reporter = base.StrReporter
        else:
            try:
                values.reporter = values.config.pcheck_reporter_factory[
                    values.reporter]
            except KeyError:
                self.error('reporter %r is not valid (known reporters: %s' % (
                        values.reporter, ', '.join(
                            repr(x)
                            for x in values.config.pcheck_reporter_factory)))

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
            values.limiters = [packages.AlwaysTrue]

        if values.checks_to_run:
            l = [convert_check_filter(x) for x in values.checks_to_run]
            values.checks = list(
                check for check in values.checks
                if any(f(qual(check)) for f in l))

        if values.checks_to_disable:
            l = [convert_check_filter(x) for x in values.checks_to_disable]
            values.checks = list(
                check for check in values.checks
                if not any(f(qual(check)) for f in l))

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


def qual(obj):
    return '%s.%s' % (obj.__module__, obj.__name__)


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

    reporter = options.reporter(out)

    transforms = list(transform(options)
                      for transform in get_plugins('transform', plugins))
    sinks = list(addon for addon in addons_map.itervalues()
                 if getattr(addon, 'feed_type', False))

    reporter.start()
    for filterer in options.limiters:
        sources = [feeds.RestrictedRepoSource(options.target_repo, filterer)]
        for pipe in base.plug(sinks, transforms, sources, reporter,
                              options.debug):
            for thing in pipe:
                pass
    reporter.finish()
    # flush stdout first; if they're directing it all to a file, this makes
    # results not get the final message shoved in midway
    out.stream.flush()
    return 0
