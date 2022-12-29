from snakeoil.cli import arghparse

from .. import reporters
from ..base import PkgcheckUserException
from .argparsers import reporter_argparser

replay = arghparse.ArgumentParser(
    prog="pkgcheck replay",
    description="replay result streams",
    parents=(reporter_argparser,),
    docs="""
        Replay previous json result streams, feeding the results into a reporter.

        Useful if you need to delay acting on results until it can be done in
        one minimal window, e.g. updating a database, or want to generate
        several different reports.
    """,
)
replay.add_argument(
    dest="results",
    metavar="FILE",
    type=arghparse.FileType("rb"),
    help="path to serialized results file",
)


@replay.bind_main_func
def _replay(options, out, err):
    processed = 0

    with options.reporter(out) as reporter:
        try:
            for result in reporters.JsonStream.from_iter(options.results):
                reporter.report(result)
                processed += 1
        except reporters.DeserializationError as e:
            if not processed:
                raise PkgcheckUserException("invalid or unsupported replay file")
            raise PkgcheckUserException(f"corrupted results file {options.results.name!r}: {e}")

    return 0
