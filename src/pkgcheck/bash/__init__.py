"""bash parsing support"""

from itertools import chain

import tree_sitter_bash
from tree_sitter import Language, Parser, Query

lang = Language(tree_sitter_bash.language())

try:
    from tree_sitter import QueryCursor

    def unstable_query(query_str: str) -> "QueryCursor":
        return QueryCursor(Query(lang, query_str))
except ImportError:  # tree-sitter < 0.25
    QueryCursor = Query
    unstable_query = lang.query


parser = Parser(language=lang)


class SortedQueryCursor:
    """
    Sort query results by line and column. It's been observed that
    query results from tree-sitter are not consistently returned in
    the same order, so this class acts as a decorator for QueryCursor
    to sort the returned captures.
    """

    def __init__(self, query_cursor: QueryCursor):
        self._query_cursor = query_cursor

    def captures(self, node):
        caps = self._query_cursor.captures(node)
        return {
            key: sorted(nodes, key=lambda n: (n.start_point.row, n.start_point.column))
            for key, nodes in caps.items()
        }


def query(query_str: str):
    return SortedQueryCursor(unstable_query(query_str))


# various parse tree queries
cmd_query = query("(command) @call")
func_query = query("(function_definition) @func")
var_assign_query = query("(variable_assignment) @assign")
var_expansion_query = query("(expansion) @exp")
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

    def global_query(self, query: QueryCursor | SortedQueryCursor):
        """Run a given parse tree query returning only those nodes in global scope."""
        for x in self.tree.root_node.children:
            # skip nodes in function scope
            if x.type != "function_definition":
                yield from chain.from_iterable(query.captures(x).values())

    def func_query(self, query: QueryCursor | SortedQueryCursor):
        """Run a given parse tree query returning only those nodes in function scope."""
        for x in self.tree.root_node.children:
            # only return nodes in function scope
            if x.type == "function_definition":
                yield from chain.from_iterable(query.captures(x).values())
