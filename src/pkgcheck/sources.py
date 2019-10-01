"""Custom package sources used for feeding checks."""

import os
from collections import OrderedDict, deque
from operator import attrgetter

from pkgcore.ebuild.repository import UnconfiguredTree
from pkgcore.restrictions import packages
from snakeoil.osutils import listdir_files, pjoin

from . import base
from .packages import FilteredPkg, RawCPV, WrappedPkg


class GenericSource:
    """Base template for a repository source."""

    feed_type = base.version_scope
    required_addons = ()

    def __init__(self, options, source=None):
        self._options = options
        self._repo = options.target_repo
        self._source = source
        self.metadata_errors = []

    @property
    def source(self):
        """Source that packages are pulled from."""
        if self._source is not None:
            return self._source
        return self._repo

    def _metadata_error(self, exc):
        self.metadata_errors.append(exc)

    def itermatch(self, restrict, **kwargs):
        """Yield packages matching the given restriction from the selected source."""
        kwargs.setdefault('sorter', sorted)
        kwargs.setdefault('error_callback', self._metadata_error)
        yield from self.source.itermatch(restrict, **kwargs)


class EmptySource(GenericSource):
    """Empty source meant for skipping feed."""

    feed_type = base.repository_scope

    def itermatch(self, restrict, **kwargs):
        yield from ()


class LatestPkgsFilter:
    """Filter source packages, yielding those from the latest non-VCS and VCS slots."""

    def __init__(self, source_iter, partial_filtered=False):
        self._partial_filtered = partial_filtered
        self._source_iter = source_iter
        self._pkg_cache = deque()
        self._pkg_marker = None

    def __iter__(self):
        return self

    def __next__(self):
        # refill pkg cache
        if not self._pkg_cache:
            if self._pkg_marker is None:
                self._pkg_marker = next(self._source_iter)
            pkg = self._pkg_marker
            key = pkg.key
            selected_pkgs = OrderedDict()
            if self._partial_filtered:
                pkgs = []

            # determine the latest non-VCS and VCS pkgs for each slot
            while key == pkg.key:
                if pkg.live:
                    selected_pkgs[f'vcs-{pkg.slot}'] = pkg
                else:
                    selected_pkgs[pkg.slot] = pkg

                if self._partial_filtered:
                    pkgs.append(pkg)

                try:
                    pkg = next(self._source_iter)
                except StopIteration:
                    self._pkg_marker = None
                    break

            if self._pkg_marker is not None:
                self._pkg_marker = pkg

            if self._partial_filtered:
                selected_pkgs = set(selected_pkgs.values())
                self._pkg_cache.extend(
                    FilteredPkg(pkg=pkg) if pkg not in selected_pkgs else pkg for pkg in pkgs)
            else:
                self._pkg_cache.extend(selected_pkgs.values())

        return self._pkg_cache.popleft()


class FilteredRepoSource(GenericSource):
    """Ebuild repository source supporting custom package filtering."""

    def __init__(self, pkg_filter, partial_filtered, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pkg_filter = pkg_filter
        self._partial_filtered = partial_filtered

    def itermatch(self, restrict, **kwargs):
        yield from self._pkg_filter(
            super().itermatch(restrict, **kwargs), partial_filtered=self._partial_filtered)


class _RawRepo(UnconfiguredTree):
    """Repository that allows matching against mismatched/invalid package names."""

    def __init__(self, repo):
        super().__init__(repo.location)

    def _get_versions(self, catpkg):
        """Pass through all packages that end with ".ebuild" extension.

        Deviates from parent in that no package name check is done.
        """
        cppath = pjoin(self.base, catpkg[0], catpkg[1])
        pkg = f'{catpkg[-1]}-'
        lp = len(pkg)
        extension = self.extension
        ext_len = -len(extension)
        try:
            return tuple(
                x[lp:ext_len] for x in listdir_files(cppath)
                if x[ext_len:] == extension)
        except EnvironmentError as e:
            path = pjoin(self.base, os.sep.join(catpkg))
            raise KeyError(f'failed fetching versions for package {path}: {e}') from e


class RawRepoSource(GenericSource):
    """Ebuild repository source returning raw CPV objects."""

    def __init__(self, *args):
        super().__init__(*args)
        self._repo = _RawRepo(self._repo)

    def itermatch(self, restrict, **kwargs):
        yield from super().itermatch(restrict, raw_pkg_cls=RawCPV, **kwargs)


class RestrictionRepoSource(GenericSource):
    """Ebuild repository source supporting custom restrictions."""

    def __init__(self, restriction, *args):
        super().__init__(*args)
        self.restriction = restriction

    def itermatch(self, restrict, **kwargs):
        restrict = packages.AndRestriction(*(restrict, self.restriction))
        yield from super().itermatch(restrict, **kwargs)


class UnmaskedRepoSource(GenericSource):
    """Repository source that uses profiles/package.mask to filter packages."""

    def itermatch(self, restrict, **kwargs):
        filtered_repo = self._options.domain.filter_repo(
            self._repo, pkg_masks=(), pkg_unmasks=(),
            pkg_accept_keywords=(), pkg_keywords=(), profile=False)
        yield from filtered_repo.itermatch(restrict, **kwargs)


class _SourcePkg(WrappedPkg):
    """Package object with file contents injected as an attribute."""

    __slots__ = ('lines',)

    def __init__(self, lines, **kwargs):
        super().__init__(**kwargs)
        self.lines = lines


class EbuildFileRepoSource(GenericSource):
    """Ebuild repository source yielding package objects and their file contents."""

    def itermatch(self, restrict, **kwargs):
        for pkg in super().itermatch(restrict, **kwargs):
            yield _SourcePkg(pkg=pkg, lines=tuple(pkg.ebuild.text_fileobj()))


class _CombinedSource(GenericSource):
    """Generic source combining packages into similar chunks."""

    def keyfunc(self, pkg):
        """Function targeting attribute used to group packages."""
        raise NotImplementedError(self.keyfunc)

    def itermatch(self, restrict, **kwargs):
        key = None
        chunk = None
        for pkg in super().itermatch(restrict, **kwargs):
            new = self.keyfunc(pkg)
            if new == key:
                chunk.append(pkg)
            else:
                if chunk is not None:
                    yield chunk
                chunk = [pkg]
                key = new
        if chunk is not None:
            yield chunk


class PackageRepoSource(_CombinedSource):
    """Ebuild repository source yielding lists of versioned packages per package."""

    feed_type = base.package_scope
    keyfunc = attrgetter('key')


class CategoryRepoSource(_CombinedSource):
    """Ebuild repository source yielding lists of versioned packages per category."""

    feed_type = base.category_scope
    keyfunc = attrgetter('category')


class RepositoryRepoSource(GenericSource):
    """Ebuild repository source yielding lists of versioned packages per package."""

    feed_type = base.repository_scope


class _FilteredSource(RawRepoSource):
    """Generic source yielding selected attribute from matching packages."""

    def keyfunc(self, pkg):
        raise NotImplementedError(self.keyfunc)

    def itermatch(self, restrict, **kwargs):
        key = None
        for pkg in super().itermatch(restrict, **kwargs):
            new = self.keyfunc(pkg)
            if new != key:
                if key is not None:
                    yield key
                key = new
        if key is not None:
            yield key


class UnversionedSource(_FilteredSource):
    """Source yielding unversioned atoms from matching packages."""

    keyfunc = attrgetter('unversioned_atom')


class VersionedSource(_FilteredSource):
    """Source yielding versioned atoms from matching packages."""

    keyfunc = attrgetter('versioned_atom')
