"""bash parsing support"""

from functools import partial
import os

from snakeoil.osutils import pjoin
from tree_sitter import Language, Parser

from . import const
from .utils import build_library


_lib_path = pjoin(os.path.dirname(__file__), '_bash-lang.so')
if not os.path.exists(_lib_path):  # pragma: no cover
    # dynamically build lib when running in git repo
    _bash_lib = pjoin(const.REPO_PATH, 'tree-sitter-bash')
    build_library(_lib_path, [_bash_lib])

lang = Language(_lib_path, 'bash')
query = partial(lang.query)
parser = Parser()
parser.set_language(lang)

# various parse tree queries
cmd_query = query('(command) @call')
func_query = query('(function_definition) @func')
var_assign_query = query('(variable_assignment) @assign')
var_query = query('(variable_name) @var')
