"""Eclass specific support and addon."""

import os
import pickle

from pkgcore.ebuild.eclass import Eclass, EclassDocParsingError
from snakeoil.cli.exceptions import UserException
from snakeoil.compatibility import IGNORED_EXCEPTIONS
from snakeoil.klass import jit_attr_none
from snakeoil.fileutils import AtomicWriteFile
from snakeoil.mappings import ImmutableDict

from . import base, caches
from .log import logger


def matching_eclass(eclasses_set, eclass):
    """Stub method for matching eclasses against a given set.

    Used to create pickleable eclass scanning restrictions.
    """
    return eclass in eclasses_set


class EclassAddon(caches.CachedAddon):
    """Eclass support for various checks."""

    # cache registry
    cache = caches.CacheData(type='eclass', file='eclass.pickle', version=1)

    def __init__(self, *args):
        super().__init__(*args)
        # mapping of repo locations to their corresponding eclass caches
        self._eclass_repos = {}

    @jit_attr_none
    def eclasses(self, repo=None):
        """Mapping of available eclasses to eclass doc info."""
        d = {}
        for r in self.options.target_repo.trees:
            d.update(self._eclass_repos.get(r.location, ()))
        return ImmutableDict(d)

    @jit_attr_none
    def deprecated(self):
        """Mapping of deprecated eclasses to their replacements (if any)."""
        d = {}
        for r in self.options.target_repo.trees:
            for k, v in self._eclass_repos.get(r.location, ()).items():
                if 'deprecated' in v:
                    d[k] = v['deprecated']
        return ImmutableDict(d)

    def update_cache(self, force=False):
        """Update related cache and push updates to disk."""
        if self.options.cache['eclass']:
            for repo in self.repos:
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
                            eclasses = {}
                    except IGNORED_EXCEPTIONS:
                        raise
                    except FileNotFoundError:
                        pass
                    except Exception as e:
                        logger.debug('forcing eclass cache regen: %s', e)
                        os.remove(cache_file)
                        eclasses = {}

                # check for eclass removals
                for name, eclass in list(eclasses.items()):
                    if not os.path.exists(eclass.path):
                        del eclasses[name]
                        cache_eclasses = True

                # verify the repo has eclasses
                repo_eclasses = repo.eclass_cache.eclasses
                if repo_eclasses:
                    # padding for progress output
                    padding = max(len(x) for x in repo_eclasses)

                    # check for eclass additions and updates
                    with base.ProgressManager(verbosity=self.options.verbosity) as progress:
                        for name, eclass in sorted(repo_eclasses.items()):
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
                            except FileNotFoundError:
                                cache_eclasses = True

                # push eclasses to disk if any changes were found
                if cache_eclasses:
                    # reset jit attrs
                    self._eclasses = None
                    self._deprecated = None
                    try:
                        os.makedirs(os.path.dirname(cache_file), exist_ok=True)
                        cache = caches.DictCache(eclasses, self.cache)
                        with AtomicWriteFile(cache_file, binary=True) as f:
                            pickle.dump(cache, f, protocol=-1)
                    except IOError as e:
                        msg = f'failed dumping eclasses: {cache_file!r}: {e.strerror}'
                        raise UserException(msg)

                self._eclass_repos[repo.location] = eclasses
