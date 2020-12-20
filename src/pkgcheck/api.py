"""Implements pkgcheck API to be exported."""

import shlex

from snakeoil.contexts import patch

from .base import PkgcheckException


def scan(args=None):
    """Run ``pkgcheck scan`` using given arguments.

    Args:
        args (str): command-line args for ``pkgcheck scan``

    Returns:
        iterator of scan results
    """
    # avoid circular imports
    from .pipeline import Pipeline
    from .scripts import pkgcheck

    def parser_exit(parser, status, message):
        """Stub function to handle argparse errors."""
        raise PkgcheckException(message)

    args = [] if args is None else shlex.split(args)

    with patch('argparse.ArgumentParser.exit', parser_exit):
        options = pkgcheck.argparser.parse_args(['scan'] + args)
    return Pipeline(options, options.restrictions)
