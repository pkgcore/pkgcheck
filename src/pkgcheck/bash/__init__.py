"""bash parsing support"""

from itertools import chain

import tree_sitter_bash
from tree_sitter import Language, Parser, Query

lang = Language(tree_sitter_bash.language())
query = lang.query
parser = Parser(language=lang)

# various parse tree queries
cmd_query = query("(command) @call")
func_query = query("(function_definition) @func")
var_assign_query = query("(variable_assignment) @assign")
var_query = query("(variable_name) @var")


class ParseTree:
    """Bash parse tree object and support."""

    def __init__(self, data: bytes, **kwargs):
        super().__init__(**kwargs)
        self.data = data
        self.tree = parser.parse(data)

    def node_str(self, node):
        """Return the ebuild string associated with a given parse tree node."""
        return self.data[node.start_byte : node.end_byte].decode("utf8")

    def global_query(self, query: Query):
        """Run a given parse tree query returning only those nodes in global scope."""
        for x in self.tree.root_node.children:
            # skip nodes in function scope
            if x.type != "function_definition":
                yield from chain.from_iterable(query.captures(x).values())

    def func_query(self, query: Query):
        """Run a given parse tree query returning only those nodes in function scope."""
        for x in self.tree.root_node.children:
            # only return nodes in function scope
            if x.type == "function_definition":
                yield from chain.from_iterable(query.captures(x).values())
