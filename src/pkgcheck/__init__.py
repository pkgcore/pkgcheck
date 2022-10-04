from importlib import import_module as _import

from .api import keywords, scan
from .base import PkgcheckException
from .results import Result

__all__ = ('keywords', 'scan', 'PkgcheckException', 'Result')
__title__ = 'pkgcheck'
__version__ = '0.10.17'


def __getattr__(name):
    """Provide import access to keyword classes."""
    if name in keywords:
        return keywords[name]

    try:
        return _import('.' + name, __name__)
    except ImportError:
        raise AttributeError(f'module {__name__} has no attribute {name}')


def __dir__():
    return sorted(__all__ + tuple(keywords))
