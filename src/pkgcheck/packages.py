"""Various custom package objects."""

from pkgcore.ebuild import atom
from snakeoil import klass


class RawCPV:
    """Raw CPV objects supporting basic restrictions/sorting."""

    __slots__ = ('category', 'package', 'fullver')

    def __init__(self, category, package, fullver):
        self.category = category
        self.package = package
        self.fullver = fullver

    def __lt__(self, other):
        if self.versioned_atom < other.versioned_atom:
            return True
        return False

    @property
    def key(self):
        return f'{self.category}/{self.package}'

    @property
    def versioned_atom(self):
        if self.fullver:
            return atom.atom(f'={self}')
        return atom.atom(str(self))

    def __str__(self):
        if self.fullver:
            return f'{self.category}/{self.package}-{self.fullver}'
        return f'{self.category}/{self.package}'

    def __repr__(self):
        address = '@%#8x' % (id(self),)
        return f'<{self.__class__} cpv={self.versioned_atom.cpvstr!r} {address}>'


class WrappedPkg:
    """Generic package wrapper used to inject attributes into package objects."""

    __slots__ = ('_pkg',)

    def __init__(self, pkg):
        self._pkg = pkg

    def __str__(self):
        return str(self._pkg)

    def __repr__(self):
        return repr(self._pkg)

    def __lt__(self, other):
        if self.versioned_atom < other.versioned_atom:
            return True
        return False

    __getattr__ = klass.GetAttrProxy('_pkg')
    __dir__ = klass.DirProxy('_pkg')


class FilteredPkg(WrappedPkg):
    """Filtered package used to mark related results that should be skipped by default."""
