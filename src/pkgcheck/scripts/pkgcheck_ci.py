import argparse

from snakeoil.cli import arghparse
from snakeoil.formatters import PlainTextFormatter

from .. import reporters, scan


class ArgumentParser(arghparse.ArgumentParser):
    """Argument parser that only parses the subcommand.

    There doesn't seem to be an easy way to make argparse move all extraneous
    args into a given argument -- using 'nargs=argparse.REMAINDER' doesn't work
    when also trying to avoid using an option since positional remainders only
    catch positional args.
    """

    def parse_known_args(self, args=None, namespace=None):
        namespace, args = super().parse_known_args(args, namespace)
        namespace.args = args
        return namespace, []


ci = ArgumentParser(prog='pkgcheck ci', description='scan repo for CI')
ci.add_argument(
    '--failures', type=argparse.FileType('w'),
    help='file path for storing failure results')


@ci.bind_main_func
def _ci(options, out, err):
    pipe = scan(options.args)

    with reporters.FancyReporter(out) as reporter:
        for result in pipe:
            reporter.report(result)
        # dump failure results to the given file
        if pipe.errors and options.failures:
            f = PlainTextFormatter(options.failures)
            with reporters.JsonStream(f) as reporter:
                for result in sorted(pipe.errors):
                    reporter.report(result)

    return int(bool(pipe.errors))
