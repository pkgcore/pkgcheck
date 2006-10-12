# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# Copyright: 2006 Marien Zwart <marienz@gentoo.org>
# License: GPL2


"""Commandline frontend (for use with L{pkgcore.util.commandline.main}."""


from pkgcore.util import commandline
from pkgcore.util.parserestrict import parse_match
from pkgcore.util.lists import stable_unique
from pkgcore.restrictions import packages
from pkgcore.util.demandload import demandload
from pkgcore.plugin import get_plugins
from pkgcore_checks import plugins

import pkgcore_checks.options
demandload(globals(), "logging time optparse textwrap "
    "pkgcore.util.osutils:normpath "
    "pkgcore.util.compatibility:any "
    "pkgcore.restrictions.values:StrRegex "
    "pkgcore_checks.base ")


class OptionParser(commandline.OptionParser):

    def __init__(self):
        commandline.OptionParser.__init__(
            self, version=pkgcore_checks.__version__,
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
        self.add_options(pkgcore_checks.options.overlay_options)

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
            values.limiters = stable_unique(map(parse_match, args))
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


def finalize_options(checks, options, runner):
    seen = set()
    for opt in pkgcore_checks.options.overlay_options:
        if isinstance(opt, pkgcore_checks.options.FinalizingOption) \
            and opt not in seen:
            opt.finalize(options, runner)
            seen.add(opt)
    for c in checks:
        for opt in c.requires:
            if isinstance(opt, pkgcore_checks.options.FinalizingOption) \
                and opt not in seen:
                opt.finalize(options, runner)
                seen.add(opt)


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
            repo = config.repo[normpath(options.repo_name)]
        except KeyError:
            err.write(
                "Error: repo %r is not a valid reponames\n "
                "known repos- [ %s ]\n" % (
                    options.repo_name,
                    ", ".join(repr(x) for x in config.repo)))
            return 1

    # XXX see if this can be eliminated
    options.pkgcore_conf = config
    options.target_repo = repo
    if not getattr(repo, "base", False):
        err.write("\nWarning: repo %s appears to be combined trees, as "
                  "such some checks will be disabled\n\n" % (
                options.repo_name,))

    if options.to_xml:
        reporter = pkgcore_checks.base.XmlReporter(out)
    else:
        reporter = pkgcore_checks.base.StrReporter(out)
    runner = pkgcore_checks.base.Feeder(repo, options)
    try:
        finalize_options(options.checks, options, runner)
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


    start_time = time.time()
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
    elapsed = time.time() - start_time
    minutes = int(elapsed)/60
    seconds = elapsed - (minutes * 60)
    # flush stdout first; if they're directing it all to a file, this makes
    # results not get a time statement shoved in midway
    out.stream.flush()
    err.write("processed %i pkgs: %im%.2fs\n" %
              (nodes, minutes, seconds))
    return 0
