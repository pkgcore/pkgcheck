import re
import string

from pkgcore.ebuild.eapi import EAPI

from .. import addons, bash, results, sources
from . import Check


class _ReservedNameCheck(Check):
    reserved_prefixes = ("__", "abort", "dyn", "prep")
    reserved_substrings = ("hook", "paludis", "portage")  # 'ebuild' is special case
    reserved_ebuild_regex = re.compile(r"(.*[^a-zA-Z])?ebuild.*")

    """Portage variables whose use is half-legitimate and harmless if the package manager doesn't support them."""
    special_whitelist = (
        "EBUILD_DEATH_HOOKS",
        "EBUILD_SUCCESS_HOOKS",
        "PORTAGE_QUIET",
        "PORTAGE_ACTUAL_DISTDIR",
    )

    """Approved good exceptions to using of variables."""
    variables_usage_whitelist = {"EBUILD_PHASE", "EBUILD_PHASE_FUNC"}

    def _check(self, used_type: str, used_names: dict[str, tuple[int, int]]):
        for used_name, (lineno, _) in used_names.items():
            if used_name in self.special_whitelist:
                continue
            test_name = used_name.lower()
            for reserved in self.reserved_prefixes:
                if test_name.startswith(reserved):
                    yield used_name, used_type, reserved, "prefix", lineno + 1
            for reserved in self.reserved_substrings:
                if reserved in test_name:
                    yield used_name, used_type, reserved, "substring", lineno + 1
            if self.reserved_ebuild_regex.match(test_name):
                yield used_name, used_type, "ebuild", "substring", lineno + 1

    def _feed(self, item: bash.ParseTree):
        yield from self._check(
            "function",
            {
                item.node_str(node.child_by_field_name("name")): node.start_point
                for node in bash.func_query.captures(item.tree.root_node).get("func", ())
            },
        )
        used_variables = {
            item.node_str(node.child_by_field_name("name")): node.start_point
            for node in bash.var_assign_query.captures(item.tree.root_node).get("assign", ())
        }
        for node in bash.var_query.captures(item.tree.root_node).get("var", ()):
            if (name := item.node_str(node)) not in self.variables_usage_whitelist:
                used_variables.setdefault(name, node.start_point)
        yield from self._check("variable", used_variables)


class EclassReservedName(results.EclassResult, results.Warning):
    """Eclass uses reserved variable or function name for package manager."""

    def __init__(
        self, used_name: str, used_type: str, reserved_word: str, reserved_type: str, **kwargs
    ):
        super().__init__(**kwargs)
        self.used_name = used_name
        self.used_type = used_type
        self.reserved_word = reserved_word
        self.reserved_type = reserved_type

    @property
    def desc(self):
        return f'{self.eclass}: {self.used_type} name "{self.used_name}" is disallowed because "{self.reserved_word}" is a reserved {self.reserved_type}'


class EclassReservedCheck(_ReservedNameCheck):
    """Scan eclasses for reserved function or variable names."""

    _source = sources.EclassParseRepoSource
    known_results = frozenset([EclassReservedName])
    required_addons = (addons.eclass.EclassAddon,)

    def __init__(self, *args, eclass_addon):
        super().__init__(*args)
        self.eclass_cache = eclass_addon.eclasses

    def feed(self, eclass: sources._ParsedEclass):
        for *args, _ in self._feed(eclass):
            yield EclassReservedName(*args, eclass=eclass.name)


class EbuildReservedName(results.LineResult, results.Warning):
    """Ebuild uses reserved variable or function name for package manager."""

    def __init__(self, used_type: str, reserved_word: str, reserved_type: str, **kwargs):
        super().__init__(**kwargs)
        self.used_type = used_type
        self.reserved_word = reserved_word
        self.reserved_type = reserved_type

    @property
    def desc(self):
        return f'line {self.lineno}: {self.used_type} name "{self.line}" is disallowed because "{self.reserved_word}" is a reserved {self.reserved_type}'


class EbuildSemiReservedName(results.LineResult, results.Warning):
    """Ebuild uses semi-reserved variable or function name.

    Ebuild is using in global scope semi-reserved variable or function names,
    which is likely to clash with future EAPIs. Currently it include
    single-letter uppercase variables, and ``[A-Z]DEPEND`` variables.
    """

    def __init__(self, used_type: str, **kwargs):
        super().__init__(**kwargs)
        self.used_type = used_type

    @property
    def desc(self):
        return f'line {self.lineno}: uses semi-reserved {self.used_type} name "{self.line}", likely to clash with future EAPIs'


class EbuildReservedCheck(_ReservedNameCheck):
    """Scan ebuilds for reserved function or variable names."""

    _source = sources.EbuildParseRepoSource
    known_results = frozenset({EbuildReservedName, EbuildSemiReservedName})

    global_reserved = (
        frozenset(string.ascii_uppercase)
        .union(c + "DEPEND" for c in string.ascii_uppercase)
        .difference(("CDEPEND",))
    )

    def __init__(self, options, **kwargs):
        super().__init__(options, **kwargs)
        self.phases_hooks = {
            eapi_name: {
                f"{prefix}_{phase}" for phase in eapi.phases.values() for prefix in ("pre", "post")
            }
            for eapi_name, eapi in EAPI.known_eapis.items()
        }

    def feed(self, pkg: sources._ParsedPkg):
        for used_name, *args, lineno in self._feed(pkg):
            yield EbuildReservedName(*args, lineno=lineno, line=used_name, pkg=pkg)

        for node in bash.func_query.captures(pkg.tree.root_node).get("func", ()):
            used_name = pkg.node_str(node.child_by_field_name("name"))
            if used_name in self.phases_hooks[str(pkg.eapi)]:
                lineno, _ = node.start_point
                yield EbuildReservedName(
                    "function", used_name, "phase hook", lineno=lineno + 1, line=used_name, pkg=pkg
                )

        current_global_reserved = self.global_reserved.difference(
            pkg.eapi.eclass_keys, pkg.eapi.dep_keys
        )
        for node in pkg.global_query(bash.var_assign_query):
            used_name = pkg.node_str(node.child_by_field_name("name"))
            if used_name in current_global_reserved:
                lineno, _ = node.start_point
                yield EbuildSemiReservedName(
                    "variable",
                    lineno=lineno + 1,
                    line=used_name,
                    pkg=pkg,
                )
