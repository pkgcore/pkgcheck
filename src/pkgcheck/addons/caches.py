"""Base cache support."""

import errno
import os
import pathlib
import pickle
import shutil
from collections import UserDict
from dataclasses import dataclass
from hashlib import blake2b
from operator import attrgetter

from snakeoil import klass
from snakeoil.compatibility import IGNORED_EXCEPTIONS
from snakeoil.fileutils import AtomicWriteFile
from snakeoil.mappings import ImmutableDict
from snakeoil.osutils import pjoin

from ..base import Addon, PkgcheckException, PkgcheckUserException
from ..log import logger


@dataclass(frozen=True)
class CacheData:
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


class CacheDisabled(PkgcheckException):
    """Exception flagging that a requested cache type is disabled."""

    def __init__(self, cache):
        super().__init__(f'{cache.type} cache support required')


class CachedAddon(Addon):
    """Mixin for addon classes that create/use data caches."""

    # attributes for cache registry
    cache = None
    # registered cache types
    caches = {}

    def __init_subclass__(cls, **kwargs):
        """Register available caches."""
        super().__init_subclass__(**kwargs)
        if cls.cache is None:
            raise ValueError(f'invalid cache registry: {cls!r}')
        cls.caches[cls] = cls.cache

    def update_cache(self, repo=None, force=False):
        """Update related cache and push updates to disk."""
        raise NotImplementedError(self.update_cache)

    def cache_file(self, repo):
        """Return the cache file for a given repository.

        A unique token using the repo's location is used so separate repos
        using the same identifier don't use the same cache file.
        """
        token = blake2b(repo.location.encode()).hexdigest()[:10]
        dirname = f'{repo.repo_id.lstrip(os.sep)}-{token}'
        return pjoin(self.options.cache_dir, 'repos', dirname, self.cache.file)

    def load_cache(self, path, fallback=None):
        cache = fallback
        try:
            with open(path, 'rb') as f:
                cache = pickle.load(f)
            if cache.version != self.cache.version:
                logger.debug(
                    'forcing %s cache regen due to outdated version', self.cache.type)
                os.remove(path)
                cache = fallback
        except IGNORED_EXCEPTIONS:
            raise
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.debug('forcing %s cache regen: %s', self.cache.type, e)
            os.remove(path)
            cache = fallback
        return cache

    def save_cache(self, data, path):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with AtomicWriteFile(path, binary=True) as f:
                pickle.dump(data, f, protocol=-1)
        except IOError as e:
            msg = f'failed dumping {self.cache.type} cache: {path!r}: {e.strerror}'
            raise PkgcheckUserException(msg)

    @klass.jit_attr
    def existing_caches(self):
        """Mapping of all existing cache types to file paths."""
        caches_map = {}
        repos_dir = pjoin(self.options.cache_dir, 'repos')
        for cache in sorted(self.caches.values(), key=attrgetter('type')):
            caches_map[cache.type] = tuple(sorted(
                pathlib.Path(repos_dir).rglob(cache.file)))
        return ImmutableDict(caches_map)

    def remove_caches(self):
        """Remove all or selected caches."""
        if self.options.force_cache:
            try:
                shutil.rmtree(self.options.cache_dir)
            except FileNotFoundError:
                pass
            except IOError as e:
                raise PkgcheckUserException(f'failed removing cache dir: {e}')
        else:
            try:
                for cache_type, paths in self.existing_caches.items():
                    if self.options.cache.get(cache_type, False):
                        for path in paths:
                            if self.options.dry_run:
                                print(f'Would remove {path}')
                            else:
                                os.unlink(path)
                                # remove empty cache dirs
                                try:
                                    while str(path) != self.options.cache_dir:
                                        os.rmdir(path.parent)
                                        path = path.parent
                                except OSError as e:
                                    if e.errno == errno.ENOTEMPTY:
                                        continue
                                    raise
            except IOError as e:
                raise PkgcheckUserException(f'failed removing {cache_type} cache: {path!r}: {e}')
