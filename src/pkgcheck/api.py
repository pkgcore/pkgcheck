"""Implements pkgcheck API to be exported."""

from snakeoil.contexts import patch

from .base import PkgcheckException


def scan(args=None, /, *, base_args=None):
    """Run ``pkgcheck scan`` using given arguments.

    Args:
        args (:obj:`list`, optional): command-line args for ``pkgcheck scan``
        base_args (:obj:`list`, optional): pkgcore-specific command-line args for ``pkgcheck``
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
    if base_args is None:
        base_args = []

    with patch('argparse.ArgumentParser.exit', parser_exit):
        options = pkgcheck.argparser.parse_args(base_args + ['scan'] + args)
    return Pipeline(options, options.restrictions)
