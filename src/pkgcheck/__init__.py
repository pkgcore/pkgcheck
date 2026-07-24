from .api import scan
from .base import PkgcheckException
from .results import Result

__all__ = ("PkgcheckException", "Result", "scan")
__title__ = "pkgcheck"
__version__ = "0.10.42.dev0"
__version_info__ = (0, 10, 42, "dev0")
__python_mininum_version__ = (3, 12, 0)
