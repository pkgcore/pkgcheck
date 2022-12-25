"""Implements pkgcheck API to be exported."""

from functools import partial

import lazy_object_proxy
from snakeoil.contexts import patch
from snakeoil.mappings import AttrAccessible

from . import objects
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
    return Pipeline(options)


def _keywords():
    """Proxy to delay module imports until keywords are requested."""

    class Keywords(AttrAccessible):
        """Mapping of keyword names to related result classes.

        Result classes are also accessible via accessing their keyword
        name as a attribute.
        """

    return Keywords(objects.KEYWORDS)


keywords = lazy_object_proxy.Proxy(partial(_keywords))
