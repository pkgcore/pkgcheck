from functools import partial
from operator import attrgetter

from pkgcore.util import commandline
from snakeoil.cli import arghparse

from .. import objects, reporters

reporter_argparser = arghparse.ArgumentParser(suppress=True)
reporter_options = reporter_argparser.add_argument_group("reporter options")
reporter_options.add_argument(
    "-R",
    "--reporter",
    action="store",
    default=None,
    help="use a non-default reporter",
    docs="""
        Select a reporter to use for output.

        Use ``pkgcheck show --reporters`` to see available options.
    """,
)
reporter_options.add_argument(
    "--format",
    dest="format_str",
    action="store",
    default=None,
    help="format string used with FormatReporter",
    docs="""
        Custom format string used to format output by FormatReporter.

        Supports python format string syntax where result object attribute names
        surrounded by curly braces are replaced with their values (if they exist).

        For example, ``--format '{category}/{package}/{package}-{version}.ebuild``
        will output ebuild paths in the target repo for results relating to
        specific ebuild versions. If a result is for the generic package (or a
        higher scope), no output will be produced for that result.

        Furthermore, no output will be produced if a result object is missing any
        requested attribute expansion in the format string. In other words,
        ``--format {foo}`` will never produce any output because no result has the
        ``foo`` attribute.
    """,
)


@reporter_argparser.bind_final_check
def _setup_reporter(parser, namespace):
    if namespace.reporter is None:
        namespace.reporter = sorted(
            objects.REPORTERS.values(), key=attrgetter("priority"), reverse=True
        )[0]
    else:
        try:
            namespace.reporter = objects.REPORTERS[namespace.reporter]
        except KeyError:
            available = ", ".join(objects.REPORTERS)
            parser.error(f"no reporter matches {namespace.reporter!r} " f"(available: {available})")

    if namespace.reporter is reporters.FormatReporter:
        if not namespace.format_str:
            parser.error("missing or empty --format option required by FormatReporter")
        namespace.reporter = partial(namespace.reporter, namespace.format_str)
    elif namespace.format_str is not None:
        parser.error("--format option is only valid when using FormatReporter")


repo_argparser = arghparse.ArgumentParser(suppress=True)
repo_options = repo_argparser.add_argument_group("repo options")
repo_options.add_argument(
    "-r",
    "--repo",
    metavar="REPO",
    dest="target_repo",
    action=commandline.StoreRepoObject,
    repo_type="ebuild-raw",
    allow_external_repos=True,
    help="target repo",
)
