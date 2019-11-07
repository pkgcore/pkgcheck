"""Base classes for check results."""

from pkgcore.ebuild import cpv
from snakeoil import klass

from . import base
from .packages import FilteredPkg, RawCPV


class _LeveledResult(type):
    """Metaclass that injects color/level attributes to raw result classes."""

    @property
    def color(cls):
        """Rendered result output color related to priority level."""
        return cls._level_to_desc[cls._level][1]

    @property
    def level(cls):
        """Result priority level."""
        return cls._level_to_desc[cls._level][0]


class Result(metaclass=_LeveledResult):
    """Generic report result returned from a check."""

    # all results are shown by default
    _filtered = False
    # default to repository level results
    scope = base.repository_scope
    # default to warning level
    _level = 30
    # level values match those used in logging module
    _level_to_desc = {
        40: ('error', 'red'),
        30: ('warning', 'yellow'),
        20: ('info', 'green'),
    }

    @property
    def color(self):
        """Rendered result output color related to priority level."""
        return self._level_to_desc[self._level][1]

    @property
    def level(self):
        """Result priority level."""
        return self._level_to_desc[self._level][0]

    def __str__(self):
        return self.desc

    @property
    def desc(self):
        """Result description."""

    @property
    def _attrs(self):
        """Return all public result attributes."""
        return {k: v for k, v in self.__dict__.items() if not k.startswith('_')}

    @staticmethod
    def attrs_to_pkg(d):
        """Reconstruct a package object from split attributes."""
        category = d.pop('category', None)
        package = d.pop('package', None)
        version = d.pop('version', None)
        if any((category, package, version)):
            pkg = RawCPV(category, package, version)
            d['pkg'] = pkg
        return d

    def __eq__(self, other):
        return self._attrs == other._attrs

    def __hash__(self):
        return hash(tuple(sorted(self._attrs)))

    def __lt__(self, other):
        if self.scope == other.scope:
            if self.__class__.__name__ == other.__class__.__name__:
                return self.desc < other.desc
            return self.__class__.__name__ < other.__class__.__name__
        return self.scope < other.scope


class Error(Result):
    """Result with an error priority level."""

    _level = 40


class Warning(Result):
    """Result with a warning priority level."""

    _level = 30


class Info(Result):
    """Result with an info priority level."""

    _level = 20


class CommitResult(Result):
    """Result related to a specific git commit."""

    scope = base.commit_scope

    def __init__(self, commit, **kwargs):
        super().__init__(**kwargs)
        self.commit = commit.commit
        self._attr = 'commit'


class CategoryResult(Result):
    """Result related to a specific category."""

    scope = base.category_scope

    def __init__(self, pkg, **kwargs):
        super().__init__(**kwargs)
        self.category = pkg.category
        self._attr = 'category'

    def __lt__(self, other):
        try:
            if self.category < other.category:
                return True
        except AttributeError:
            pass
        return super().__lt__(other)


class PackageResult(CategoryResult):
    """Result related to a specific package."""

    scope = base.package_scope

    def __init__(self, pkg, **kwargs):
        super().__init__(pkg, **kwargs)
        self.package = pkg.package
        self._attr = 'package'

    def __lt__(self, other):
        try:
            if self.package < other.package:
                return True
        except AttributeError:
            pass
        return super().__lt__(other)


class VersionedResult(PackageResult):
    """Result related to a specific version of a package."""

    scope = base.version_scope

    def __init__(self, pkg, **kwargs):
        super().__init__(pkg, **kwargs)
        self.version = pkg.fullver
        self._attr = 'version'

    @klass.jit_attr
    def ver_rev(self):
        version, _, revision = self.version.partition('-r')
        revision = cpv._Revision(revision)
        return version, revision

    def __lt__(self, other):
        try:
            cmp = cpv.ver_cmp(*(self.ver_rev + other.ver_rev))
            if cmp < 0:
                return True
            elif cmp > 0:
                return False
        except AttributeError:
            pass
        return super().__lt__(other)


class FilteredVersionResult(VersionedResult):
    """Result that will be optionally filtered for old packages by default."""

    def __init__(self, pkg, **kwargs):
        if isinstance(pkg, FilteredPkg):
            self._filtered = True
            pkg = pkg._pkg
        super().__init__(pkg, **kwargs)


class _LogResult(Result):
    """Message caught from a logger instance."""

    def __init__(self, msg):
        super().__init__()
        self.msg = msg

    @property
    def desc(self):
        return self.msg


class LogWarning(_LogResult, Warning):
    """Warning caught from a logger instance."""


class LogError(_LogResult, Error):
    """Error caught from a logger instance."""


class _RegisterMetadataErrors(_LeveledResult):
    """Metaclass for register known metadata results."""

    def __new__(cls, name, bases, class_dict):
        new_cls = type.__new__(cls, name, bases, class_dict)
        if new_cls._metadata_attrs:
            for attr in new_cls._metadata_attrs:
                setting = new_cls.result_mapping.setdefault(attr, new_cls)
                if setting != new_cls:
                    raise ValueError(
                        f'metadata attribute {attr!r} already registered: {setting!r}')
        elif new_cls.__name__ != 'MetadataError':
            raise ValueError(f'class missing metadata attributes: {new_cls!r}')
        return new_cls


class MetadataError(VersionedResult, Error, metaclass=_RegisterMetadataErrors):
    """Problem detected with a package's metadata."""

    # specific metadata attributes handled by the result class
    _metadata_attrs = ()
    # mapping from data attributes to result classes
    result_mapping = {}

    def __init__(self, attr, msg, **kwargs):
        super().__init__(**kwargs)
        self.attr = attr
        self.msg = str(msg)

    @property
    def desc(self):
        if self._metadata_attrs:
            return self.msg
        else:
            return f'attr({self.attr}): {self.msg}'
