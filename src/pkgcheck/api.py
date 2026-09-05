"""Implements pkgcheck API to be exported."""

__all__ = ("scan",)


from unittest.mock import patch

from .base import PkgcheckException


def scan(args=None, /, *, base_args=None, sandbox=False):
    """Run ``pkgcheck scan`` using given arguments.

    Args:
        args (:obj:`list`, optional): command-line args for ``pkgcheck scan``
        base_args (:obj:`list`, optional): pkgcore-specific command-line args for ``pkgcheck``
        sandbox (:obj:`bool`, optional): confine the calling process for the
            scan. Disabled by default, as Landlock restrictions cannot be
            lifted afterwards.
    Raises:
        PkgcheckException on failure
    Returns:
        iterator of Result objects
    """
    # avoid circular imports
    from .pipeline import Pipeline
    from .scripts import pkgcheck

    def parser_exit(parser, status=0, message=None):
        """Stub function to handle argparse errors.

        Exit calls with no message arguments signify truncated scans, i.e. no
        restriction targets are specified.
        """
        if message:
            raise PkgcheckException(message.strip())

    if args is None:
        args = []
    if base_args is None:
        base_args = []

    with patch("argparse.ArgumentParser.exit", parser_exit):
        options = pkgcheck.argparser.parse_args(base_args + ["scan"] + args)
    if sandbox:
        from .sandbox import confine

        confine(options)
    return Pipeline(options)
