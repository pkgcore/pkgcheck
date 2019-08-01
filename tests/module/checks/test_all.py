from importlib import import_module
import inspect
import pkgutil

from pkgcheck import base, checks


def find_classes(module, parent_cls):
    """Scan under a module path searching for child classes inheriting a given parent."""
    mod_path = getattr(module, '__path__')
    mod_name = getattr(module, '__name__')
    for imp, name, _ in pkgutil.walk_packages(mod_path, f'{mod_name}.'):
        # skip "private" modules
        if name.rsplit('.', 1)[1][0] == '_':
            continue
        try:
            m = import_module(name)
        except ImportError as e:
            raise Exception(f'failed importing {name!r}: {e}')
        for name, cls in inspect.getmembers(m):
            if inspect.isclass(cls) and issubclass(cls, parent_cls) and name[0] != '_':
                yield name, cls


_known_keywords = set()

def test_checks():
    """Scan through all public checks and verify various aspects."""
    for name, cls in find_classes(checks, base.Template):
        assert cls.known_results, f"check class {name!r} doesn't define known results"
        _known_keywords.update(cls.known_results)


def test_keywords():
    """Scan through all public result keywords and verify various aspects."""
    for name, cls in find_classes(checks, base.Result):
        assert cls in _known_keywords, f"result class {name!r} not used by any checks"
