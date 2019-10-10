"""Core classes and interfaces.

This defines a couple of standard feed types and scopes. Currently
feed types are strings and scopes are integers, but you should use the
symbolic names wherever possible (everywhere except for adding a new
feed type) since this might change in the future. Scopes are integers,
but do not rely on that either.

Feed types have to match exactly. Scopes are ordered: they define a
minimally accepted scope.
"""

import concurrent.futures
import os
import re
import shutil
import sys
from contextlib import AbstractContextManager

from pkgcore import const as pkgcore_const
from snakeoil.mappings import ImmutableDict
from snakeoil.osutils import pjoin


class Scope:
    """Generic scope for scans, checks, and results."""

    def __init__(self, desc, level):
        self.desc = desc
        self.level = level

    def __str__(self):
        return self.desc

    def __repr__(self):
        address = '@%#8x' % (id(self),)
        return f'<{self.__class__.__name__} desc={self.desc!r} {address}>'

    def __lt__(self, other):
        return self.level < other.level

    def __gt__(self, other):
        return self.level > other.level

    def __le__(self, other):
        return self.level <= other.level

    def __ge__(self, other):
        return self.level >= other.level

    def __eq__(self, other):
        return self.level == other.level

    def __hash__(self):
        return hash(self.level)


version_scope = Scope('version', 0)
package_scope = Scope('package', 1)
category_scope = Scope('category', 2)
repository_scope = Scope('repository', 3)
commit_scope = Scope('commit', 4)

# mapping for -S/--scopes option, ordered for sorted output in the case of unknown scopes
scopes = ImmutableDict({
    'git': commit_scope,
    'repo': repository_scope,
    'cat': category_scope,
    'pkg': package_scope,
    'ver': version_scope,
})

CACHE_DIR = pjoin(pkgcore_const.USER_CACHE_PATH, 'pkgcheck')


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


class Cache:
    """Mixin for addon classes that create/use data caches."""

    # used to check on-disk cache compatibility
    cache_version = 0
    # used by cache subcommand
    cache_type = None
    _cache_file = None

    def update_cache(self, force=False):
        """Update related cache and push updates to disk."""
        raise NotImplementedError(self.update_cache)

    @staticmethod
    def cache_dir(repo):
        """Return the cache directory for a given repository."""
        return pjoin(CACHE_DIR, 'repos', repo.repo_id.lstrip(os.sep))

    def cache_file(self, repo):
        """Return the cache file for a given repository."""
        return pjoin(self.cache_dir(repo), self._cache_file)

    @staticmethod
    def update_caches(options, addons):
        """Update all known caches."""
        ret = []
        force = getattr(options, 'force_cache', False)
        with concurrent.futures.ThreadPoolExecutor() as executor:
            futures = [
                executor.submit(addon.update_cache, force)
                for addon in addons]
            for future in concurrent.futures.as_completed(futures):
                ret.append(future.result())
        return any(ret)

    def remove_cache(self):
        """Remove selected caches."""
        raise NotImplementedError(self.remove_cache)

    @staticmethod
    def remove_caches(options, addons):
        """Remove all or selected caches."""
        ret = []
        force = getattr(options, 'force_cache', False)
        if force:
            try:
                shutil.rmtree(CACHE_DIR)
            except FileNotFoundError:
                pass
            except IOError as e:
                raise UserException(f'failed removing cache dir: {e}')
            ret.append(0)
        else:
            with concurrent.futures.ThreadPoolExecutor() as executor:
                futures = [executor.submit(addon.remove_cache) for addon in addons]
                for future in concurrent.futures.as_completed(futures):
                    ret.append(future.result())
        return any(ret)


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
            c for c in checks
            if any(p(f'{c.__module__}.{c.__name__}') for p in self.patterns))


class Blacklist(_CheckSet):
    """Only run checks not matching any of the provided patterns."""

    def filter(self, checks):
        return list(
            c for c in checks
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
