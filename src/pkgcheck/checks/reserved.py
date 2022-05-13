import re
from .. import addons, bash, results, sources
from . import Check


class _ReservedNameCheck(Check):
    reserved_prefixes = ('__', 'abort', 'dyn', 'prep')
    reserved_substrings = ('hook', 'paludis', 'portage')  # 'ebuild' is special case
    reserved_ebuild_regex = re.compile(r'(.*[^a-zA-Z])?ebuild.*')

    """Portage variables whose use is half-legitimate and harmless if the package manager doesn't support them."""
    special_whitelist = ('EBUILD_DEATH_HOOKS', 'EBUILD_SUCCESS_HOOKS', 'PORTAGE_QUIET')

    def _check(self, used_type: str, used_names):
        for used_name, node_start in used_names.items():
            if used_name in self.special_whitelist:
                continue
            test_name = used_name.lower()
            lineno, _ = node_start
            for reserved in self.reserved_prefixes:
                if test_name.startswith(reserved):
                    yield used_name, used_type, reserved, 'prefix', lineno
            for reserved in self.reserved_substrings:
                if reserved in test_name:
                    yield used_name, used_type, reserved, 'substring', lineno
            if self.reserved_ebuild_regex.match(test_name):
                yield used_name, used_type, 'ebuild', 'substring', lineno

    def _feed(self, item):
        yield from self._check('function', {
            item.node_str(node.child_by_field_name('name')): node.start_point
            for node, _ in bash.func_query.captures(item.tree.root_node)
        })
        yield from self._check('variable', {
            item.node_str(node.child_by_field_name('name')): node.start_point
            for node, _ in bash.var_assign_query.captures(item.tree.root_node)
        })


class EclassReservedName(results.EclassResult, results.Warning):
    """Eclass uses reserved variable or function name for package manager."""

    def __init__(self, used_name: str, used_type: str, reserved_word: str, reserved_type: str, **kwargs):
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

    def feed(self, eclass):
        for *args, _ in self._feed(eclass):
            yield EclassReservedName(*args, eclass=eclass.name)


class EbuildReservedName(results.LineResult, results.Warning):
    """Ebuild uses reserved variable or function name for package manager."""

    def __init__(self, used_name: str, used_type: str, reserved_word: str, reserved_type: str, **kwargs):
        super().__init__(**kwargs)
        self.used_name = used_name
        self.used_type = used_type
        self.reserved_word = reserved_word
        self.reserved_type = reserved_type

    @property
    def desc(self):
        return f'line {self.lineno}: {self.used_type} name "{self.used_name}" is disallowed because "{self.reserved_word}" is a reserved {self.reserved_type}'


class EbuildReservedCheck(_ReservedNameCheck):
    """Scan ebuilds for reserved function or variable names."""

    _source = sources.EbuildParseRepoSource
    known_results = frozenset([EbuildReservedName])

    def feed(self, pkg):
        for *args, lineno in self._feed(pkg):
            yield EbuildReservedName(*args, lineno=lineno, line='', pkg=pkg)
