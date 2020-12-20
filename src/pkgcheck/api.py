"""Implements pkgcheck API to be exported."""

from snakeoil.contexts import patch

from .base import PkgcheckException


def scan(args=None):
    """Run ``pkgcheck scan`` using given arguments.

    Args:
        args (list): command-line args for ``pkgcheck scan``
    Raises:
        PkgcheckException on failure
    Returns:
        iterator of Result objects
    """
    # avoid circular imports
    from .pipeline import Pipeline
    from .scripts import pkgcheck

    def parser_exit(parser, status, message):
        """Stub function to handle argparse errors."""
        raise PkgcheckException(message)

    if args is None:
        args = []

    with patch('argparse.ArgumentParser.exit', parser_exit):
        options = pkgcheck.argparser.parse_args(['scan'] + args)
    return Pipeline(options, options.restrictions)
