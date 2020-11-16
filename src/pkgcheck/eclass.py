"""Eclass specific support and addon."""

from collections import UserDict
import os
import pickle

from pkgcore.ebuild.eclass import Eclass, EclassDocParsingError
from snakeoil import klass
from snakeoil.cli.exceptions import UserException
from snakeoil.fileutils import AtomicWriteFile
from snakeoil.mappings import ImmutableDict

from . import base, caches
from .log import logger


class _EclassCache(UserDict, caches.Cache):
    """Cache that encapsulates eclass data."""

    def __init__(self, data):
        super().__init__(data)
        self._cache = EclassAddon.cache


class EclassAddon(caches.CachedAddon):
    """Eclass support for various checks."""

    # cache registry
    cache = caches.CacheData(type='eclass', file='eclass.pickle', version=1)

    def __init__(self, *args):
        super().__init__(*args)
        self.eclasses = {}

    @klass.jit_attr
    def deprecated(self):
        """Mapping of deprecated eclasses to their replacements (if any)."""
        return ImmutableDict({
            k: v['deprecated']
            for k, v in self.eclasses.items() if 'deprecated' in v
        })

    def update_cache(self, force=False):
        """Update related cache and push updates to disk."""
        if self.options.cache['eclass']:
            repos = (r for r in self.repos if 'gentoo' in r.aliases)
            for repo in repos:
                cache_file = self.cache_file(repo)
                cache_eclasses = False
                eclasses = {}

                if not force:
                    # try loading cached eclass data
                    try:
                        with open(cache_file, 'rb') as f:
                            eclasses = pickle.load(f)
                        if eclasses.version != self.cache.version:
                            logger.debug('forcing eclass repo cache regen due to outdated version')
                            os.remove(cache_file)
                    except FileNotFoundError:
                        pass
                    except (AttributeError, EOFError, ImportError, IndexError) as e:
                        logger.debug('forcing eclass cache regen: %s', e)
                        os.remove(cache_file)

                # check for eclass removals
                for name, eclass in list(eclasses.items()):
                    if not os.path.exists(eclass.path):
                        del eclasses[name]
                        cache_eclasses = True

                # padding for progress output
                padding = max(len(x) for x in repo.eclass_cache.eclasses)

                # check for eclass additions and updates
                with base.ProgressManager(verbosity=self.options.verbosity) as progress:
                    for name, eclass in sorted(repo.eclass_cache.eclasses.items()):
                        try:
                            if os.path.getmtime(eclass.path) != eclasses[name].mtime:
                                raise KeyError
                        except (KeyError, AttributeError):
                            try:
                                progress(f'updating eclass cache: {name:<{padding}}')
                                eclasses[name] = Eclass(eclass.path, sourced=True)
                                cache_eclasses = True
                            except (IOError, EclassDocParsingError):
                                continue

                # push eclasses to disk if any changes were found
                if cache_eclasses:
                    try:
                        os.makedirs(os.path.dirname(cache_file), exist_ok=True)
                        f = AtomicWriteFile(cache_file, binary=True)
                        f.write(pickle.dumps(_EclassCache(eclasses)))
                        f.close()
                    except IOError as e:
                        msg = f'failed dumping eclasses: {cache_file!r}: {e.strerror}'
                        raise UserException(msg)

                self.eclasses = eclasses
