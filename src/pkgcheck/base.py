"""Core classes and interfaces.

This defines a couple of standard feed types and scopes. Currently
feed types are strings and scopes are integers, but you should use the
symbolic names wherever possible (everywhere except for adding a new
feed type) since this might change in the future. Scopes are integers,
but do not rely on that either.

Feed types have to match exactly. Scopes are ordered: they define a
minimally accepted scope.
"""

import re
import sys
import typing
from contextlib import AbstractContextManager, ExitStack, contextmanager
from dataclasses import dataclass
from functools import partial
from itertools import chain

from snakeoil.cli.exceptions import UserException
from snakeoil.contexts import patch
from snakeoil.mappings import ImmutableDict


@dataclass(frozen=True, eq=False)
class Scope:
    """Generic scope for scans, checks, and results."""

    desc: str
    level: int
    _children: tuple = ()

    def __str__(self):
        return f"{self.__class__.__name__}({self.desc!r})"

    def __lt__(self, other):
        if isinstance(other, Scope):
            return self.level < other.level
        return self.level < other

    def __le__(self, other):
        if isinstance(other, Scope):
            return self.level <= other.level
        return self.level <= other

    def __gt__(self, other):
        if isinstance(other, Scope):
            return self.level > other.level
        return self.level > other

    def __ge__(self, other):
        if isinstance(other, Scope):
            return self.level >= other.level
        return self.level >= other

    def __eq__(self, other):
        if isinstance(other, Scope):
            return self.desc == other.desc
        return self.level == other

    def __hash__(self):
        return hash(self.desc)

    def __repr__(self):
        address = "@%#8x" % (id(self),)
        return f"<{self.__class__.__name__} desc={self.desc!r} {address}>"

    def __contains__(self, key):
        return self == key or key in self._children

    def __iter__(self):
        return chain([self], self._children)


@dataclass(repr=False, frozen=True, eq=False)
class PackageScope(Scope):
    """Scope for package-specific checks."""


@dataclass(repr=False, frozen=True, eq=False)
class ConditionalScope(Scope):
    """Scope for checks run only in certain circumstances."""

    level: int = -99


@dataclass(repr=False, frozen=True, eq=False)
class LocationScope(Scope):
    """Scope for location-specific checks."""

    level: int = 0


# pkg-related scopes (level increasing by granularity)
repo_scope = PackageScope("repo", 1)
category_scope = PackageScope("category", 2)
package_scope = PackageScope("package", 3)
version_scope = PackageScope("version", 4)

# conditional (negative level) and location-specific scopes (zero level)
commit_scope = ConditionalScope("commit")
profile_node_scope = LocationScope("profile_node")
profiles_scope = LocationScope("profiles", 0, (profile_node_scope,))
eclass_scope = LocationScope("eclass")

# mapping for -S/--scopes option, ordered for sorted output in the case of unknown scopes
scopes = ImmutableDict(
    {
        "git": commit_scope,
        "profiles": profiles_scope,
        "eclass": eclass_scope,
        "repo": repo_scope,
        "cat": category_scope,
        "pkg": package_scope,
        "ver": version_scope,
    }
)


class PkgcheckException(Exception):
    """Generic pkgcheck exception."""


class PkgcheckUserException(PkgcheckException, UserException):
    """Generic pkgcheck exception for user-facing cli output.."""


class Addon:
    """Base class for extra functionality for pkgcheck other than a check.

    The checkers can depend on one or more of these. They will get
    called at various points where they can extend pkgcheck (if any
    active checks depend on the addon).

    These methods are not part of the checker interface because that
    would mean addon functionality shared by checkers would run twice.
    They are not plugins because they do not do anything useful if no
    checker depending on them is active.

    This interface is not finished. Expect it to grow more methods
    (but if not overridden they will be no-ops).

    :cvar required_addons: sequence of addon dependencies
    """

    required_addons = ()

    def __init__(self, options, **kwargs):
        """Initialize.

        An instance of every addon in required_addons is passed as extra arg.

        :param options: the argparse values.
        """
        self.options = options

    @staticmethod
    def mangle_argparser(parser):
        """Add extra options and/or groups to the argparser.

        This hook is always triggered, even if the checker is not
        activated (because it runs before the commandline is parsed).

        :param parser: an C{argparse.ArgumentParser} instance.
        """


def get_addons(objects):
    """Return tuple of addons for a given sequence of objects."""
    addons = {}

    def _addons(objs):
        """Recursively determine addons that are requested."""
        for addon in objs:
            if addon not in addons:
                if addon.required_addons:
                    _addons(addon.required_addons)
                addons[addon] = None

    _addons(objects)
    return tuple(addons)


def param_name(cls):
    """Restructure class names for injected parameters.

    For example, GitAddon -> git_addon and GitCache -> git_cache.
    """
    return re.sub(r"([a-z])([A-Z])", r"\1_\2", cls.__name__).lower()


@dataclass(frozen=True)
class LogMap:
    """Log function to callable mapping."""

    func: str
    call: typing.Callable


@contextmanager
def LogReports(*logmaps):
    """Context manager for turning log messages into results."""
    reports = []

    def report(call, x):
        reports.append(call(x))

    try:
        with ExitStack() as stack:
            for x in logmaps:
                stack.enter_context(patch(x.func, partial(report, x.call)))
            yield reports
    finally:
        pass


class ProgressManager(AbstractContextManager):
    """Context manager for handling progressive output.

    Useful for updating the user about the status of a long running process.
    """

    def __init__(self, verbosity=0):
        self.verbosity = verbosity
        self._cached = None

    def _progress_callback(self, s):
        """Callback used for progressive output."""
        # avoid rewriting the same output
        if s != self._cached:
            sys.stderr.write(f"{s}\r")
            self._cached = s

    def __enter__(self):
        if self.verbosity >= 0 and sys.stdout.isatty():
            return self._progress_callback
        return lambda x: None

    def __exit__(self, _exc_type, _exc_value, _traceback):
        if self._cached is not None:
            sys.stderr.write("\n")
