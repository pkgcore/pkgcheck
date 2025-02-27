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


class SuboptimalCratesURICall(results.LineResult, results.Warning):
    """Calling ``cargo_crate_uris`` with ``CRATES`` is suboptimal, use
    ``${CARGO_CRATE_URIS}``.

    Calls to ``$(cargo_crate_uris)`` and ``$(cargo_crate_uris ${CRATES})`` are
    suboptimal, and can be replaces with ``${CARGO_CRATE_URIS}`` which is
    pre-computed, faster and doesn't require sub-shell in global-scope.
    """

    @property
    def desc(self):
        return f"line: {self.lineno}: calling {self.line!r} is suboptimal, use '${{CARGO_CRATE_URIS}}' for global CRATES instead"


class TooManyCrates(results.VersionResult, results.Warning):
    """Too many crates in ``CRATES`` variable.

    The ``CRATES`` variable is a space-separated list of crates. When it has
    more than 300 crates, it can cause performance issues for metadata
    generation and package manager handling. It is recommended to use a crates
    tarball instead.
    """

    def __init__(self, count: int, **kwargs):
        super().__init__(**kwargs)
        self.count = count

    @property
    def desc(self):
        return f"CRATES variable has {self.count} crates, consider using crates tarball instead"


class RustCheck(Check):
    """Checks for rust related issues."""

    _source = sources.EbuildParseRepoSource
    known_results = frozenset(
        {
            SuboptimalCratesSeparator,
            SuboptimalCratesURICall,
            TooManyCrates,
        }
    )

    def _verify_crates(self, pkg: bash.ParseTree):
        for node in pkg.global_query(bash.var_assign_query):
            name = pkg.node_str(node.child_by_field_name("name"))
            if name == "CRATES":
                val_node = node.children[-1]
                row, _ = val_node.start_point
                val_str = pkg.node_str(val_node).strip("'\"")
                crates = val_str.split()
                if len(crates) > 300:
                    yield TooManyCrates(count=len(crates), pkg=pkg)
                for lineno, line in enumerate(crates, start=row + 1):
                    for token in line.split():
                        if "@" not in token:
                            yield SuboptimalCratesSeparator(
                                lineno=lineno,
                                line=token,
                                pkg=pkg,
                            )
                            return

    def _verify_cargo_crate_uris(self, pkg: bash.ParseTree):
        for node in bash.cmd_query.captures(pkg.tree.root_node).get("call", ()):
            call_name = pkg.node_str(node.child_by_field_name("name"))
            if call_name == "cargo_crate_uris":
                row, _ = node.start_point
                line = pkg.node_str(node.parent).strip()
                if node.child_count == 1 or (
                    node.child_count == 2
                    and any(
                        pkg.node_str(var_node) == "CRATES"
                        for var_node in bash.var_query.captures(node.children[1]).get("var", ())
                    )
                ):
                    yield SuboptimalCratesURICall(
                        lineno=row + 1,
                        line=line,
                        pkg=pkg,
                    )
                    break

    def feed(self, pkg: bash.ParseTree):
        if "cargo" not in pkg.inherited:
            return
        yield from self._verify_crates(pkg)
        yield from self._verify_cargo_crate_uris(pkg)
