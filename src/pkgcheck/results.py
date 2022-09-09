"""Base classes for check results."""

from functools import total_ordering

from pkgcore.ebuild import cpv
from snakeoil import klass
from snakeoil.strings import pluralism

from . import base
from .packages import FilteredPkg, RawCPV


class InvalidResult(Exception):
    """Creating a result object failed in some fashion."""


@total_ordering
class Result:
    """Generic report result returned from a check."""

    # all results are shown by default
    _filtered = False
    # default to repository level results
    scope = base.repo_scope
    # priority level, color, name, and profile type
    level = None
    color = None
    _name = None
    _profile = None

    def __init_subclass__(cls, **kwargs):
        """Initialize result subclasses and set 'name' class attribute."""
        super().__init_subclass__(**kwargs)
        cls.name = cls._name if cls._name is not None else cls.__name__

    def __str__(self):
        return f'{self.name}: {self.desc}'

    @property
    def desc(self):
        """Result description."""

    @property
    def _attrs(self):
        """Return all public result attributes."""
        return {k: v for k, v in self.__dict__.items() if not k.startswith('_')}

    @classmethod
    def _create(cls, **kwargs):
        """Create a new result object from a given attributes dict."""
        if issubclass(cls, CategoryResult):
            category = kwargs.pop('category', None)
            package = kwargs.pop('package', None)
            version = kwargs.pop('version', None)
            if 'pkg' not in kwargs:
                # recreate pkg param from related, separated attributes
                if category is None:
                    raise InvalidResult('missing category')
                if issubclass(cls, PackageResult) and package is None:
                    raise InvalidResult('missing package')
                if issubclass(cls, VersionResult) and version is None:
                    raise InvalidResult('missing version')
                kwargs['pkg'] = RawCPV(category, package, version)
        return cls(**kwargs)

    def __eq__(self, other):
        return self.name == other.name and self._attrs == other._attrs

    def __hash__(self):
        return hash((self.name, tuple(sorted(self._attrs.items()))))

    def __lt__(self, other):
        if self.scope == other.scope:
            if self.name == other.name:
                return self.desc < other.desc
            return self.name < other.name
        return self.scope < other.scope


class AliasResult(Result):
    """Classes directly inheriting this class can be targeted as scannable keywords."""


class BaseLinesResult:
    """Base class for results of multiples lines."""

    def __init__(self, lines, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.lines = tuple(lines)

    @property
    def lines_str(self):
        s = pluralism(self.lines)
        lines = ', '.join(map(str, self.lines))
        return f'on line{s}: {lines}'


class Error(Result):
    """Result with an error priority level."""

    level = 'error'
    color = 'red'


class Warning(Result):
    """Result with a warning priority level."""

    level = 'warning'
    color = 'yellow'


class Style(Result):
    """Result with a coding style priority level."""

    level = 'style'
    color = 'cyan'


class Info(Result):
    """Result with an info priority level."""

    level = 'info'
    color = 'green'


class CommitResult(Result):
    """Result related to a specific git commit."""

    scope = base.commit_scope

    def __init__(self, commit, **kwargs):
        super().__init__(**kwargs)
        self.commit = str(commit)
        self._attr = 'commit'

    def __lt__(self, other):
        try:
            # if hashes match, sort by name/desc
            if self.commit == other.commit:
                if self.name == other.name:
                    return self.desc < other.desc
                return self.name < other.name
        except AttributeError:
            pass
        return False


class ProfilesResult(Result):
    """Result related to profiles."""

    scope = base.profiles_scope


class EclassResult(Result):
    """Result related to a specific eclass."""

    scope = base.eclass_scope

    def __init__(self, eclass, **kwargs):
        super().__init__(**kwargs)
        self.eclass = str(eclass)
        self._attr = 'eclass'

    def __lt__(self, other):
        try:
            # if eclasses match, sort by name/desc
            if self.eclass == other.eclass:
                if self.name == other.name:
                    return self.desc < other.desc
                return self.name < other.name
            return self.eclass < other.eclass
        except AttributeError:
            pass
        return False


class CategoryResult(Result):
    """Result related to a specific category."""

    scope = base.category_scope

    def __init__(self, pkg, **kwargs):
        super().__init__(**kwargs)
        self.category = pkg.category
        self._attr = 'category'

    def __lt__(self, other):
        try:
            if self.category != other.category:
                return self.category < other.category
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
            if self.category == other.category and self.package != other.package:
                return self.package < other.package
        except AttributeError:
            pass
        return super().__lt__(other)


class VersionResult(PackageResult):
    """Result related to a specific version of a package."""

    scope = base.version_scope

    def __init__(self, pkg, **kwargs):
        if isinstance(pkg, FilteredPkg):
            self._filtered = True
            pkg = pkg._pkg
        super().__init__(pkg, **kwargs)
        self.version = pkg.fullver
        self._attr = 'version'

    @klass.jit_attr
    def ver_rev(self):
        version, _, revision = self.version.partition('-r')
        revision = cpv.Revision(revision)
        return version, revision

    def __lt__(self, other, cmp=None):
        try:
            if self.category == other.category and self.package == other.package:
                if cmp is None:
                    cmp = cpv.ver_cmp(*(self.ver_rev + other.ver_rev))
                if cmp < 0:
                    return True
                elif cmp > 0:
                    return False
        except AttributeError:
            pass
        return super().__lt__(other)


class LinesResult(BaseLinesResult, VersionResult):
    """Result related to multiples lines of an ebuild."""


class LineResult(VersionResult):
    """Result related to a specific line of an ebuild."""

    def __init__(self, line, lineno, **kwargs):
        super().__init__(**kwargs)
        self.line = line
        self.lineno = lineno

    def __lt__(self, other):
        cmp = None
        try:
            if self.category == other.category and self.package == other.package:
                # sort by line number for matching versions
                cmp = cpv.ver_cmp(*(self.ver_rev + other.ver_rev))
                if cmp == 0:
                    if self.lineno < other.lineno:
                        return True
                    elif self.lineno > other.lineno:
                        return False
        except AttributeError:
            pass
        return super().__lt__(other, cmp=cmp)


class _LogResult(Result):
    """Message caught from a logger instance."""

    def __init__(self, msg):
        super().__init__()
        self.msg = str(msg)

    @property
    def desc(self):
        return self.msg


class LogWarning(_LogResult, Warning):
    """Warning caught from a logger instance."""


class LogError(_LogResult, Error):
    """Error caught from a logger instance."""


class MetadataError(Error):
    """Problem detected with a package's metadata."""

    # specific metadata attributes handled by the result class
    attr = None
    # mapping from data attributes to result classes
    results = {}

    def __init_subclass__(cls, **kwargs):
        """Register metadata attribute error results."""
        super().__init_subclass__(**kwargs)
        if cls.attr is not None:
            setting = cls.results.setdefault(cls.attr, cls)
            if setting != cls:
                raise ValueError(
                    f'metadata attribute {cls.attr!r} already registered: {setting!r}')
        else:
            raise ValueError(f'class missing metadata attributes: {cls!r}')

    def __init__(self, attr, msg, **kwargs):
        super().__init__(**kwargs)
        self.attr = attr
        self.msg = str(msg)

    @property
    def desc(self):
        return self.msg
