# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# Copyright: 2006 Marien Zwart <marienz@gentoo.org>
# License: GPL2


"""Commandline frontend (for use with L{pkgcore.util.commandline.main}."""


from pkgcore.util import commandline, parserestrict, lists, demandload
from pkgcore.util.compatibility import any
from pkgcore.restrictions import packages
from pkgcore.plugin import get_plugins
from pkgcore_checks import (
    plugins, base, options as pcheck_options, __version__)

demandload.demandload(globals(), "logging optparse textwrap "
    "pkgcore.util:osutils "
    "pkgcore.repository:multiplex "
    "pkgcore.ebuild:repository "
    "pkgcore.restrictions.values:StrRegex ")


class OptionParser(commandline.OptionParser):

    def __init__(self):
        commandline.OptionParser.__init__(
            self, version=__version__,
            description="pkgcore based ebuild QA checks",
            usage="usage: %prog repository [options] [atom1...atom2]")

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
            "-r", "--overlayed-repo", action='store', dest='metadata_src_repo',
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

        values.repo_name = args.pop(0)
        if args:
            values.limiters = lists.stable_unique(map(
                    parserestrict.parse_match, args))
        else:
            values.limiters = [packages.AlwaysTrue]

        if values.checks_to_run:
            l = [convert_check_filter(x) for x in values.checks_to_run]
            values.checks = filter_checks(values.checks,
                                          lambda x:any(y.match(x) for y in l))

        if values.checks_to_disable:
            l = [convert_check_filter(x) for x in values.checks_to_disable]
            values.checks = filter_checks(values.checks,
                                          lambda x: not any(y.match(x)
                                                            for y in l))

        return values, ()


def convert_check_filter(tok):
    tok = tok.lower()
    if not ('+' in tok or '*' in tok):
        tok = "^(?:[^.]+\.)*%s(?:\.[^.]+)*$" % tok
    return StrRegex(tok, case_sensitive=False)


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

def filter_checks(checks, filter_func):
    l = []
    for x in checks:
        if filter_func("%s.%s" % (x.__module__, x.__name__)):
            l.append(x)
    return l


def main(config, options, out, err):
    """Do stuff."""

    if options.list_checks:
        display_checks(out, options.checks)
        return 0

    try:
        repo = config.repo[options.repo_name]
    except KeyError:
        try:
            repo = config.repo[osutils.normpath(options.repo_name)]
        except KeyError:
            err.write(
                "Error: repo %r is not a valid reponames\n "
                "known repos- [ %s ]\n" % (
                    options.repo_name,
                    ", ".join(repr(x) for x in config.repo)))
            return 1

    options.target_repo = repo
    if not getattr(repo, "base", False):
        err.write("\nWarning: repo %s appears to be combined trees, as "
                  "such some checks will be disabled\n\n" % (
                options.repo_name,))

    if options.to_xml:
        reporter = base.XmlReporter(out)
    else:
        reporter = base.StrReporter(out)
    runner = base.Feeder(repo, options)

    # Finalize overlay stuff.
    if options.metadata_src_repo is None:
        options.repo_base = None
        options.src_repo = options.target_repo
    else:
        try:
            repo = config.repo[options.metadata_src_repo]
        except KeyError:
            err.write(
                "Error: overlayed-repo %r isn't a known repo\n" % (
                    options.metadata_src_repo,))
            return -1

        if not isinstance(repo, repository.UnconfiguredTree):
            err.write(
                "overlayed-repo %r isn't a "
                "pkgcore.ebuild.repository.UnconfiguredTree instance; "
                "must specify a raw ebuild repo, not type %r: %r" % (
                    options.metadata_src.repo, repo.__class__, repo))
            return -1

        options.src_repo = repo
        options.repo_base = osutils.abspath(repo.base)
        runner.search_repo = multiplex.tree(options.target_repo,
                                            options.src_repo)

    seen = set()
    try:
        for c in options.checks:
            for opt in c.requires:
                if (isinstance(opt, pcheck_options.FinalizingOption)
                    and opt not in seen):
                    opt.finalize(options, runner)
                    seen.add(opt)
    except optparse.OptionValueError, ov:
        err.write("arg processing failed: see --help\n%s\n" % str(ov))
        return -1

    for obj in options.checks:
        try:
            runner.add_check(obj)
        except SystemExit:
            raise
        except Exception:
            logging.exception("test %s failed to be added" % (obj,))
            if options.debug:
                raise

    nodes = 0
    err.write("checks: repo(%i), cat(%i), pkg(%i), version(%i)\n" %
              (len(runner.repo_checks), len(runner.cat_checks),
               len(runner.pkg_checks), len(runner.ver_checks)))

    if not (runner.repo_checks or runner.cat_checks or runner.pkg_checks or
            runner.ver_checks):
        err.write("no tests\n")
        return 1
    reporter.start()
    for filterer in options.limiters:
        nodes += runner.run(reporter, filterer)
    reporter.finish()
    # flush stdout first; if they're directing it all to a file, this makes
    # results not get the final message shoved in midway
    out.stream.flush()
    err.write("processed %i pkgs\n" % (nodes,))
    return 0
