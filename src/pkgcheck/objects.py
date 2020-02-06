"""Registration for keywords, checks, and reporters."""

from collections.abc import Mapping
import inspect
import os
import pkgutil
from importlib import import_module

from snakeoil import klass

from . import __title__ as _pkg

try:
    # This is a file written during installation;
    # if it exists, we defer to it. If it doesn't, then we're
    # running from a git checkout or a tarball.
    from . import _const as _defaults
except ImportError:
    _defaults = klass._sentinel


def _find_modules(module):
    """Generator of all public modules under a given module."""
    if getattr(module, '__path__', False):
        for _imp, name, _ in pkgutil.walk_packages(module.__path__, module.__name__ + '.'):
            # skip "private" modules
            if name.rsplit('.', 1)[1][0] == '_':
                continue
            try:
                yield import_module(name)
            except ImportError as e:
                raise Exception(f'failed importing {name!r}: {e}')
    else:
        yield module


def _find_classes(module, matching_cls):
    """Generator of all subclasses of a selected class under a given module."""
    for _name, cls in inspect.getmembers(module):
        if (inspect.isclass(cls) and issubclass(cls, matching_cls)
                and cls.__name__[0] != '_'):
            yield cls


def _find_obj_classes(module_name, target_cls):
    """Determine mapping of object class names to class objects."""
    module = import_module(f'.{module_name}', _pkg)
    cls_module, cls_name = target_cls.rsplit('.', 1)
    matching_cls = getattr(import_module(f'.{cls_module}', _pkg), cls_name)

    # skip top-level, base classes
    base_classes = {matching_cls.__name__: matching_cls}
    if os.path.basename(module.__file__) == '__init__.py':
        for cls in _find_classes(module, matching_cls):
            base_classes[cls.__name__] = cls

    classes = {}
    for m in _find_modules(module):
        for cls in _find_classes(m, matching_cls):
            if cls.__name__ in base_classes:
                continue
            if cls.__name__ in classes and classes[cls.__name__] != cls:
                raise Exception(f'object name overlap: {cls} and {classes[cls.__name__]}')
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
        if _defaults is klass._sentinel:
            self._dict

    @klass.jit_attr
    def _dict(self):
        try:
            result = getattr(_defaults, self._attr)
        except AttributeError:
            result = _find_obj_classes(*self._func_args)
        return dict(result)

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


KEYWORDS = _LazyDict('KEYWORDS', ('checks', 'results.Result'))
CHECKS = _LazyDict('CHECKS', ('checks', 'checks.Check'))
REPORTERS = _LazyDict('REPORTERS', ('reporters', 'reporters.Reporter'))
