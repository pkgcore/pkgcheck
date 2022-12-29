"""Registration for keywords, checks, and reporters."""

import inspect
import os
import pkgutil
from collections.abc import Mapping
from functools import partial
from importlib import import_module

from snakeoil import klass
from snakeoil.mappings import ImmutableDict

try:
    # This is a file written during installation;
    # if it exists, we defer to it. If it doesn't, then we're
    # running from a git checkout or a tarball.
    from . import _objects as _defaults
except ImportError:  # pragma: no cover
    _defaults = klass.sentinel


def _find_modules(module):  # pragma: no cover
    """Generator of all public modules under a given module."""
    if getattr(module, "__path__", False):
        for _imp, name, _ in pkgutil.walk_packages(module.__path__, module.__name__ + "."):
            # skip "private" modules
            if name.rsplit(".", 1)[1][0] == "_":
                continue
            try:
                yield import_module(name)
            except ImportError as e:
                raise Exception(f"failed importing {name!r}: {e}")
    else:
        yield module


def _find_classes(module, matching_cls, skip=()):  # pragma: no cover
    """Generator of all subclasses of a selected class under a given module."""
    for _name, cls in inspect.getmembers(module):
        if (
            inspect.isclass(cls)
            and issubclass(cls, matching_cls)
            and cls.__name__[0] != "_"
            and cls not in skip
        ):
            yield cls


def _find_obj_classes(module_name, target_cls):  # pragma: no cover
    """Determine mapping of object class names to class objects."""
    module = import_module(f".{module_name}", "pkgcheck")
    cls_module, cls_name = target_cls.rsplit(".", 1)
    matching_cls = getattr(import_module(f".{cls_module}", "pkgcheck"), cls_name)

    # skip top-level, base classes
    base_classes = {matching_cls}
    if os.path.basename(module.__file__) == "__init__.py":
        base_classes.update(_find_classes(module, matching_cls))

    classes = {}
    for m in _find_modules(module):
        for cls in _find_classes(m, matching_cls, skip=base_classes):
            if cls.__name__ in classes and classes[cls.__name__] != cls:
                raise Exception(f"object name overlap: {cls} and {classes[cls.__name__]}")
            classes[cls.__name__] = cls

    return classes


class _LazyDict(Mapping):
    """Lazy dictionary of object mappings.

    Used to stall module imports to avoid cyclic import issues."""

    def __init__(self, attr, func_args):
        self._attr = attr
        self._func_args = func_args

        # Forcibly collapse mapping when running from the git repo, used to
        # force cache registration to occur as related modules are imported.
        if _defaults is klass.sentinel:  # pragma: no cover
            self._dict

    @klass.jit_attr
    def _dict(self):
        try:
            result = getattr(_defaults, self._attr)
        except AttributeError:  # pragma: no cover
            result = _find_obj_classes(*self._func_args)
        return ImmutableDict(result)

    def __iter__(self):
        return iter(self._dict.keys())

    def __len__(self):
        return len(list(self._dict.keys()))

    def __getitem__(self, key):
        return self._dict[key]

    def keys(self):
        return iter(self._dict.keys())

    def values(self):
        return iter(self._dict.values())

    def items(self):
        return iter(self._dict.items())

    def select(self, cls):
        """Return mapping of object classes inheriting a given class."""
        return {k: v for k, v in self._dict.items() if issubclass(v, cls)}


def _keyword_alias(alias=None):
    """Decorator to register keyword aliases."""

    class decorator:
        """Decorator with access to the class of a decorated function."""

        def __init__(self, func):
            self.func = func

        def __set_name__(self, cls, name):
            key = alias if alias is not None else name
            cls._alias_keywords.add(key)
            jit_attr = klass.jit_attr_named(f"_{self.func.__name__}")
            func = jit_attr(partial(self.func))
            setattr(cls, name, func)

    return decorator


class _KeywordsLazyDict(_LazyDict):
    """Lazy dictionary of keyword mappings with added filtered attributes."""

    _alias_keywords = set()

    @klass.jit_attr
    def aliases(self):
        """Mapping of aliases to their respective mappings."""
        from . import results

        alias_map = {x: getattr(self, x) for x in self._alias_keywords}
        # support class-based aliasing
        for k, v in self._dict.items():
            if results.AliasResult in v.__bases__:
                alias_map[k] = self.select(v)
        return ImmutableDict(alias_map)

    @_keyword_alias()
    def error(self):
        """Mapping of all error level keywords."""
        from . import results

        return ImmutableDict(self.select(results.Error))

    @_keyword_alias()
    def warning(self):
        """Mapping of all warning level keywords."""
        from . import results

        return ImmutableDict(self.select(results.Warning))

    @_keyword_alias()
    def style(self):
        """Mapping of all style level keywords."""
        from . import results

        return ImmutableDict(self.select(results.Style))

    @_keyword_alias()
    def info(self):
        """Mapping of all info level keywords."""
        from . import results

        return ImmutableDict(self.select(results.Info))

    @klass.jit_attr
    def filter(self):
        """Mapping of default result filters."""
        return ImmutableDict()


class _ChecksLazyDict(_LazyDict):
    """Lazy dictionary of keyword mappings with added filtered attributes."""

    @klass.jit_attr
    def default(self):
        """Mapping of all default-enabled checks."""
        from . import checks

        return ImmutableDict(
            {k: v for k, v in self._dict.items() if not issubclass(v, checks.OptionalCheck)}
        )


KEYWORDS = _KeywordsLazyDict("KEYWORDS", ("checks", "results.Result"))
CHECKS = _ChecksLazyDict("CHECKS", ("checks", "checks.Check"))
REPORTERS = _LazyDict("REPORTERS", ("reporters", "reporters.Reporter"))
