"""Base cache support."""

import errno
import os
import pathlib
import shutil
from collections import UserDict
from operator import attrgetter
from typing import NamedTuple

from snakeoil import klass
from snakeoil.cli.exceptions import UserException
from snakeoil.mappings import ImmutableDict
from snakeoil.osutils import pjoin

from . import base, const


class CacheData(NamedTuple):
    """Cache registry data."""
    type: str
    file: str
    version: int


class Cache:
    """Mixin for data caches."""

    __getattr__ = klass.GetAttrProxy('_cache')


class DictCache(UserDict, Cache):
    """Dictionary-based cache that encapsulates data."""

    def __init__(self, data, cache):
        super().__init__(data)
        self._cache = cache


class _RegisterCache(type):
    """Metaclass for registering caches."""

    def __new__(cls, name, bases, class_dict):
        new_cls = type.__new__(cls, name, bases, class_dict)
        if new_cls.__name__ != 'CachedAddon':
            if new_cls.cache is None:
                raise ValueError(f'invalid cache registry: {new_cls!r}')
            new_cls.caches[new_cls] = new_cls.cache
        return new_cls


class CachedAddon(base.Addon, metaclass=_RegisterCache):
    """Mixin for addon classes that create/use data caches."""

    # attributes for cache registry
    cache = None
    # registered cache types
    caches = {}

    def update_cache(self, force=False):
        """Update related cache and push updates to disk."""
        raise NotImplementedError(self.update_cache)

    @klass.jit_attr
    def cache_dir(self):
        """Return the cache directory for a given repository."""
        path = getattr(self.options, 'cache_dir', const.USER_CACHE_DIR)
        return os.path.realpath(path)

    def cache_file(self, repo):
        """Return the cache file for a given repository."""
        return pjoin(
            self.cache_dir, 'repos',
            repo.repo_id.lstrip(os.sep), self.cache.file)

    @property
    def repos(self):
        """Relevant repositories to target for cache operations."""
        try:
            # running from scan subcommand
            return self.options.target_repo.trees
        except AttributeError:
            # running from cache subcommand
            return self.options.domain.ebuild_repos

    @klass.jit_attr
    def existing_caches(self):
        """Mapping of all existing cache types to file paths."""
        caches_map = {}
        repos_dir = pjoin(self.cache_dir, 'repos')
        for cache in sorted(self.caches.values(), key=attrgetter('type')):
            caches_map[cache.type] = tuple(sorted(
                pathlib.Path(repos_dir).rglob(cache.file)))
        return ImmutableDict(caches_map)

    def remove_caches(self):
        """Remove all or selected caches."""
        force = getattr(self.options, 'force_cache', False)
        if force:
            try:
                shutil.rmtree(self.cache_dir)
            except FileNotFoundError:
                pass
            except IOError as e:
                raise UserException(f'failed removing cache dir: {e}')
        else:
            try:
                for cache_type, paths in self.existing_caches.items():
                    if self.options.cache.get(cache_type, False):
                        for path in paths:
                            if self.options.dry_run:
                                print(f'Would remove {path}')
                            else:
                                path.unlink()
                                # remove empty cache dirs
                                try:
                                    while str(path) != self.cache_dir:
                                        path.parent.rmdir()
                                        path = path.parent
                                except OSError as e:
                                    if e.errno == errno.ENOTEMPTY:
                                        continue
                                    raise
            except IOError as e:
                raise UserException(f'failed removing {cache_type} cache: {path!r}: {e}')
