"""Various custom package objects."""

from dataclasses import dataclass, field
from functools import total_ordering

from pkgcore.ebuild import atom, cpv
from snakeoil import klass


@total_ordering
@dataclass(frozen=True, eq=False)
class RawCPV:
    """Raw CPV objects supporting basic restrictions/sorting."""

    category: str
    package: str
    fullver: str
    version: str = field(init=False, default=None)
    revision: cpv.Revision = field(init=False, default=None)

    def __post_init__(self):
        if self.fullver is not None:
            version, _, revision = self.fullver.partition("-r")
            object.__setattr__(self, "version", version)
            object.__setattr__(self, "revision", cpv.Revision(revision))

    @property
    def key(self):
        return f"{self.category}/{self.package}"

    @property
    def versioned_atom(self):
        if self.fullver:
            return atom.atom(f"={self}")
        return atom.atom(str(self))

    @property
    def unversioned_atom(self):
        return atom.atom(self.key)

    def __lt__(self, other):
        return self.versioned_atom < other.versioned_atom

    def __eq__(self, other):
        return self.versioned_atom == other.versioned_atom

    def __str__(self):
        if self.fullver:
            return f"{self.category}/{self.package}-{self.fullver}"
        return f"{self.category}/{self.package}"

    def __repr__(self):
        address = "@%#8x" % (id(self),)
        return f"<{self.__class__.__name__} cpv={self.versioned_atom.cpvstr!r} {address}>"


@total_ordering
class WrappedPkg:
    """Generic package wrapper used to inject attributes into package objects."""

    __slots__ = ("_pkg",)

    def __init__(self, pkg):
        self._pkg = pkg

    def __str__(self):
        return str(self._pkg)

    def __repr__(self):
        return repr(self._pkg)

    def __lt__(self, other):
        return self.versioned_atom < other.versioned_atom

    def __eq__(self, other):
        return self.versioned_atom == other.versioned_atom

    def __hash__(self):
        return hash(self._pkg)

    __getattr__ = klass.GetAttrProxy("_pkg")
    __dir__ = klass.DirProxy("_pkg")


class FilteredPkg(WrappedPkg):
    """Filtered package used to mark related results that should be skipped by default."""
