"""Internal constants."""

import os
import sys

from snakeoil import mappings

from . import __title__ as _pkg

_reporoot = os.path.realpath(__file__).rsplit(os.path.sep, 3)[0]
_module = sys.modules[__name__]

try:
    # This is a file written during installation;
    # if it exists, we defer to it. If it doesn't, then we're
    # running from a git checkout or a tarball.
    from . import _const as _defaults
except ImportError:
    _defaults = object()


def _GET_CONST(attr, default_value, allow_environment_override=False):
    consts = mappings.ProxiedAttrs(_module)
    default_value %= consts

    result = getattr(_defaults, attr, default_value)
    if allow_environment_override:
        result = os.environ.get(f'{_pkg.upper()}_OVERRIDE_{attr}', result)
    return result


# determine XDG compatible paths
for xdg_var, var_name, fallback_dir in (
        ('XDG_CONFIG_HOME', 'USER_CONFIG_PATH', '~/.config'),
        ('XDG_CACHE_HOME', 'USER_CACHE_PATH', '~/.cache'),
        ('XDG_DATA_HOME', 'USER_DATA_PATH', '~/.local/share')):
    setattr(
        _module, var_name,
        os.environ.get(xdg_var, os.path.join(os.path.expanduser(fallback_dir), _pkg)))

USER_CACHE_DIR = getattr(_module, 'USER_CACHE_PATH')
USER_CONF_FILE = os.path.join(getattr(_module, 'USER_CONFIG_PATH'), f'{_pkg}.conf')
SYSTEM_CONF_FILE = f'/etc/{_pkg}/{_pkg}.conf'

REPO_PATH = _GET_CONST('REPO_PATH', _reporoot, allow_environment_override=True)
DATA_PATH = _GET_CONST('DATA_PATH', '%(REPO_PATH)s/data')
