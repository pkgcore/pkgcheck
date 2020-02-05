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
from contextlib import AbstractContextManager

from pkgcore import const as pkgcore_const
from snakeoil.mappings import ImmutableDict


class Scope:
    """Generic scope for scans, checks, and results."""

    def __init__(self, desc, level, attrs=()):
        self.desc = desc
        self.level = level
        self.attrs = attrs

    def __str__(self):
        return self.desc

    def __repr__(self):
        address = '@%#8x' % (id(self),)
        return f'<{self.__class__.__name__} desc={self.desc!r} {address}>'

    def __lt__(self, other):
        if isinstance(other, Scope):
            return self.level < other.level
        return self.level < other

    def __gt__(self, other):
        if isinstance(other, Scope):
            return self.level > other.level
        return self.level > other

    def __le__(self, other):
        if isinstance(other, Scope):
            return self.level <= other.level
        return self.level <= other

    def __ge__(self, other):
        if isinstance(other, Scope):
            return self.level >= other.level
        return self.level >= other

    def __eq__(self, other):
        if isinstance(other, Scope):
            return self.level == other.level
        return self.level == other

    def __hash__(self):
        return hash(self.desc)


# pkg-related scope levels
repo_scope = Scope('repo', 1)
category_scope = Scope('category', 2, ('category',))
package_scope = Scope('package', 3, ('category', 'package'))
version_scope = Scope('version', 4, ('category', 'package', 'version'))

# Special scope levels, scopes with negative levels are only enabled under
# certain circumstances while location specific scopes have a level of 0.
commit_scope = Scope('commit', -1, ('commit',))
profiles_scope = Scope('profiles', 0)
eclass_scope = Scope('eclass', 0, ('eclass',))

# mapping for -S/--scopes option, ordered for sorted output in the case of unknown scopes
scopes = ImmutableDict({
    'git': commit_scope,
    'profiles': profiles_scope,
    'eclass': eclass_scope,
    'repo': repo_scope,
    'cat': category_scope,
    'pkg': package_scope,
    'ver': version_scope,
})


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

    :cvar required_addons: sequence of addons this one depends on.
    """

    required_addons = ()

    def __init__(self, options):
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

    @staticmethod
    def check_args(parser, namespace):
        """Postprocess the argparse values.

        Should raise C{argparse.ArgumentError} on failure.

        This is only called for addons that are enabled, but before
        they are instantiated.
        """


def convert_check_filter(tok):
    """Convert an input string into a filter function.

    The filter function accepts a qualified python identifier string
    and returns a bool.

    The input can be a regexp or a simple string. A simple string must
    match a component of the qualified name exactly. A regexp is
    matched against the entire qualified name.

    Matches are case-insensitive.

    Examples::

      convert_check_filter('foo')('a.foo.b') == True
      convert_check_filter('foo')('a.foobar') == False
      convert_check_filter('foo.*')('a.foobar') == False
      convert_check_filter('foo.*')('foobar') == True
    """
    tok = tok.lower()
    if '+' in tok or '*' in tok:
        return re.compile(tok, re.I).match
    else:
        toklist = tok.split('.')

        def func(name):
            chunks = name.lower().split('.')
            if len(toklist) > len(chunks):
                return False
            for i in range(len(chunks)):
                if chunks[i:i + len(toklist)] == toklist:
                    return True
            return False

        return func


class _CheckSet:
    """Run only listed checks."""

    # No config hint here since this one is abstract.

    def __init__(self, patterns):
        self.patterns = list(convert_check_filter(pat) for pat in patterns)


class Whitelist(_CheckSet):
    """Only run checks matching one of the provided patterns."""

    def filter(self, checks):
        return list(
            c for c in set(checks)
            if any(p(f'{c.__module__}.{c.__name__}') for p in self.patterns))


class Blacklist(_CheckSet):
    """Only run checks not matching any of the provided patterns."""

    def filter(self, checks):
        return list(
            c for c in set(checks)
            if not any(p(f'{c.__module__}.{c.__name__}') for p in self.patterns))


def filter_update(objs, enabled=(), disabled=()):
    """Filter a given list of check or result types."""
    if enabled:
        whitelist = Whitelist(enabled)
        objs = list(whitelist.filter(objs))
    if disabled:
        blacklist = Blacklist(disabled)
        objs = list(blacklist.filter(objs))
    return objs


def param_name(cls):
    """Restructure class names for injected parameters.

    For example, GitAddon -> git_addon and GitCache -> git_cache.
    """
    return re.sub(r'([a-z])([A-Z])', r'\1_\2', cls.__name__).lower()


class ProgressManager(AbstractContextManager):
    """Context manager for handling progressive output.

    Useful for updating the user about the status of a long running process.
    """

    def __init__(self, debug=False):
        self.debug = debug
        self._triggered = False

    def _progress_callback(self, s):
        """Callback used for progressive output."""
        sys.stderr.write(f'{s}\r')
        self._triggered = True

    def __enter__(self):
        if self.debug:
            return self._progress_callback
        else:
            return lambda x: None

    def __exit__(self, _exc_type, _exc_value, _traceback):
        if self._triggered:
            sys.stderr.write('\n')
