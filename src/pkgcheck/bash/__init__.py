"""bash parsing support"""

from functools import partial
import os

from snakeoil.osutils import pjoin
from tree_sitter import Language, Parser

from .. import const

from ctypes.util import find_library

# path to bash parsing library on the system (may be None)
syslib = find_library('tree-sitter-bash')

# path to bash parsing library (vendored)
lib = pjoin(os.path.dirname(__file__), 'lang.so')

# copied from tree-sitter with the following changes:
# - prefer stdc++ over c++ when linking
# - perform platform-specific compiler customizations
def build_library(output_path, repo_paths):  # pragma: no cover
    """
    Build a dynamic library at the given path, based on the parser
    repositories at the given paths.

    Returns `True` if the dynamic library was compiled and `False` if
    the library already existed and was modified more recently than
    any of the source files.
    """
    from distutils.ccompiler import new_compiler
    from distutils.sysconfig import customize_compiler
    from distutils.unixccompiler import UnixCCompiler
    from os import path
    from platform import system
    from tempfile import TemporaryDirectory

    output_mtime = path.getmtime(output_path) if path.exists(output_path) else 0

    if not repo_paths:
        raise ValueError("Must provide at least one language folder")

    cpp = False
    source_paths = []
    for repo_path in repo_paths:
        src_path = path.join(repo_path, "src")
        source_paths.append(path.join(src_path, "parser.c"))
        if path.exists(path.join(src_path, "scanner.cc")):
            cpp = True
            source_paths.append(path.join(src_path, "scanner.cc"))
        elif path.exists(path.join(src_path, "scanner.c")):
            source_paths.append(path.join(src_path, "scanner.c"))
    source_mtimes = [path.getmtime(__file__)] + [
        path.getmtime(path_) for path_ in source_paths
    ]

    compiler = new_compiler()
    # force `c++` compiler so the appropriate standard library is used
    if isinstance(compiler, UnixCCompiler):
        compiler.compiler_cxx[0] = "c++"

    if max(source_mtimes) <= output_mtime:
        return False

    # perform platform-specific compiler customizations
    customize_compiler(compiler)

    with TemporaryDirectory(suffix="tree_sitter_language") as out_dir:
        object_paths = []
        for source_path in source_paths:
            flags = []
            if system() != "Windows" and source_path.endswith(".c"):
                flags.append("-std=c99")
            object_paths.append(
                compiler.compile(
                    [source_path],
                    output_dir=out_dir,
                    include_dirs=[path.dirname(source_path)],
                    extra_preargs=flags,
                )[0]
            )
        compiler.link_shared_object(
            object_paths,
            output_path,
            target_lang="c++" if cpp else "c",
        )
    return True


try:
    from .. import _const
except ImportError:  # pragma: no cover
    # build library when running from git repo or tarball
    if syslib is None and not os.path.exists(lib) and 'tree-sitter-bash' in os.listdir(const.REPO_PATH):
        bash_src = pjoin(const.REPO_PATH, 'tree-sitter-bash')
        build_library(lib, [bash_src])

if syslib is not None or os.path.exists(lib):
    lang = Language(syslib or lib, 'bash')
    query = partial(lang.query)
    parser = Parser()
    parser.set_language(lang)

    # various parse tree queries
    cmd_query = query('(command) @call')
    func_query = query('(function_definition) @func')
    var_assign_query = query('(variable_assignment) @assign')
    var_query = query('(variable_name) @var')


class ParseTree:
    """Bash parse tree object and support."""

    def __init__(self, data, **kwargs):
        super().__init__(**kwargs)
        self.data = data
        self.tree = parser.parse(data)

    def node_str(self, node):
        """Return the ebuild string associated with a given parse tree node."""
        return self.data[node.start_byte:node.end_byte].decode('utf8')

    def global_query(self, query):
        """Run a given parse tree query returning only those nodes in global scope."""
        for x in self.tree.root_node.children:
            # skip nodes in function scope
            if x.type != 'function_definition':
                for node, _ in query.captures(x):
                    yield node

    def func_query(self, query):
        """Run a given parse tree query returning only those nodes in function scope."""
        for x in self.tree.root_node.children:
            # only return nodes in function scope
            if x.type == 'function_definition':
                for node, _ in query.captures(x):
                    yield node
