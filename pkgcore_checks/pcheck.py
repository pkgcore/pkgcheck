# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# Copyright: 2006 Marien Zwart <marienz@gentoo.org>
# License: GPL2


"""Commandline frontend (for use with L{pkgcore.util.commandline.main}."""


import optparse

from pkgcore.util import commandline, parserestrict, lists, demandload
from pkgcore.util.compatibility import any
from pkgcore.restrictions import packages
from pkgcore.plugin import get_plugins
from pkgcore_checks import (
    plugins, base, options as pcheck_options, __version__)

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

    parser.values.repo_base = osutils.abspath(repo.base)


class OptionParser(commandline.OptionParser):

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
            "-x", "--xml", action="store_true", default=False,
            dest="to_xml", help="dump xml formated result")

        overlay = self.add_option_group('Overlay')
        overlay.add_option(
            "-r", "--overlayed-repo", action='callback', type='string',
            callback=metadata_src_callback,
            help="if the target repository is an overlay, specify the "
            "repository name to pull profiles/license from")

        # yes linear, but not a huge issue.
        new_opts = []
        for c in get_plugins('check', plugins):
            for opt in c.requires:
                if isinstance(opt, optparse.Option) and opt not in new_opts:
                    new_opts.append(opt)
        if new_opts:
            self.add_options(new_opts)

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

        if values.src_repo is None:
            values.src_repo = values.target_repo
            values.search_repo = values.target_repo
        else:
            values.search_repo = multiplex.tree(values.target_repo,
                                                values.src_repo)

        if args:
            values.limiters = lists.stable_unique(map(
                    parserestrict.parse_match, args))
        else:
            values.limiters = [packages.AlwaysTrue]

        if values.checks_to_run:
            l = [convert_check_filter(x) for x in values.checks_to_enable]
            values.checks = list(
                check for check in values.checks
                if any(f(qual(check)) for f in l))

        if values.checks_to_disable:
            l = [convert_check_filter(x) for x in values.checks_to_disable]
            values.checks = list(
                check for check in values.checks
                if not any(f(qual(check)) for f in l))

        values.runner = base.Feeder(values.target_repo, values)
        seen = set()
        try:
            for c in values.checks:
                for opt in c.requires:
                    if (isinstance(opt, pcheck_options.FinalizingOption)
                        and opt not in seen):
                        opt.finalize(values, values.runner)
                        seen.add(opt)
        except optparse.OptionValueError, e:
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
                    out.write(line)
        else:
            out.write("No Documentation")
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

    if not getattr(options.target_repo, "base", False):
        err.write(
            'Warning: target repo appears to be combined trees, as '
            'such some checks will be disabled\n')

    if options.to_xml:
        reporter = base.XmlReporter(out)
    else:
        reporter = base.StrReporter(out)

    for obj in options.checks:
        try:
            options.runner.add_check(obj)
        except (SystemExit, KeyboardInterrupt):
            raise
        except Exception:
            logging.exception("test %s failed to be added" % (obj,))
            if options.debug:
                raise

    nodes = 0
    err.write("checks: repo(%i), cat(%i), pkg(%i), version(%i)" %
              (len(options.runner.repo_checks), len(options.runner.cat_checks),
               len(options.runner.pkg_checks), len(options.runner.ver_checks)))

    if not (options.runner.repo_checks or options.runner.cat_checks or
            options.runner.pkg_checks or options.runner.ver_checks):
        err.write("no tests")
        return 1
    reporter.start()
    for filterer in options.limiters:
        nodes += options.runner.run(reporter, filterer)
    reporter.finish()
    # flush stdout first; if they're directing it all to a file, this makes
    # results not get the final message shoved in midway
    out.stream.flush()
    err.write("processed %i pkgs" % (nodes,))
    return 0
