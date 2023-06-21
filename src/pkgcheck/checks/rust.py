from .. import bash, results, sources
from . import Check


class SuboptimalCratesSeparator(results.LineResult, results.Warning):
    """Using ``-`` as name-version separator in ``CRATES`` is suboptimal.

    The ``CRATES`` variable is a space separated list of crates. The eclass
    supports specifying the crate name and version as ``name@version`` and as
    ``name-version``. The latter is suboptimal as it's slower.

    It is recommended to use ``pycargoebuild`` 0.7+ to generate new ``CRATES``.
    """

    @property
    def desc(self):
        return f"line: {self.lineno}: using - as name-version separator in CRATES is suboptimal, use name@version instead"


class RustCheck(Check):
    """Checks for rust related issues."""

    _source = sources.EbuildParseRepoSource
    known_results = frozenset(
        {
            SuboptimalCratesSeparator,
        }
    )

    def _verify_crates(self, pkg: bash.ParseTree):
        for node in pkg.global_query(bash.var_assign_query):
            name = pkg.node_str(node.child_by_field_name("name"))
            if name == "CRATES":
                val_node = node.children[-1]
                row, _ = val_node.start_point
                val_str = pkg.node_str(val_node).strip("'\"")
                for lineno, line in enumerate(val_str.splitlines(), start=row + 1):
                    for token in line.split():
                        if "@" not in token:
                            yield SuboptimalCratesSeparator(
                                lineno=lineno,
                                line=token,
                                pkg=pkg,
                            )
                            return

    def feed(self, pkg: bash.ParseTree):
        if "cargo" not in pkg.inherited:
            return
        yield from self._verify_crates(pkg)
