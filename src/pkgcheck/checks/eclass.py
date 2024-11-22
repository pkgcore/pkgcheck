import shlex
import subprocess
from collections import defaultdict
from functools import partial

from pkgcore.ebuild.atom import atom as atom_cls
from pkgcore.ebuild.eapi import EAPI
from pkgcore.ebuild.eclass import EclassDoc
from snakeoil.sequences import iflatten_instance
from snakeoil.strings import pluralism

from .. import addons, bash, results, sources
from ..base import LogMap, LogReports
from . import Check
from .codingstyle import VariableScope, VariableScopeCheck


class DeprecatedEclass(results.VersionResult, results.Warning):
    """Package uses an eclass that is deprecated/abandoned."""

    def __init__(self, eclass, replacement, **kwargs):
        super().__init__(**kwargs)
        self.eclass = eclass
        self.replacement = replacement

    @property
    def desc(self):
        if self.replacement is not None:
            replacement = f"migrate to {self.replacement}"
        else:
            replacement = "no replacement"
        return f"uses deprecated eclass: {self.eclass} ({replacement})"


class DeprecatedEclassVariable(results.LineResult, results.Warning):
    """Package uses a deprecated variable from an eclass."""

    def __init__(self, variable, replacement, **kwargs):
        super().__init__(**kwargs)
        self.variable = variable
        self.replacement = replacement

    @property
    def desc(self):
        if self.replacement is not None:
            replacement = f"migrate to {self.replacement}"
        else:
            replacement = "no replacement"
        return f"uses deprecated variable on line {self.lineno}: {self.variable} ({replacement})"


class EclassUserVariableUsage(results.LineResult, results.Warning):
    """Package uses a user variable from an eclass."""

    def __init__(self, eclass, **kwargs):
        super().__init__(**kwargs)
        self.eclass = eclass

    @property
    def desc(self):
        return f"line {self.lineno}: uses user variable {self.line!r} from eclass {self.eclass!r}"


class DeprecatedEclassFunction(results.LineResult, results.Warning):
    """Package uses a deprecated function from an eclass."""

    def __init__(self, function, replacement, **kwargs):
        super().__init__(**kwargs)
        self.function = function
        self.replacement = replacement

    @property
    def desc(self):
        if self.replacement is not None:
            replacement = f"migrate to {self.replacement}"
        else:
            replacement = "no replacement"
        return f"uses deprecated function on line {self.lineno}: {self.function} ({replacement})"


class DuplicateEclassInherit(results.LineResult, results.Style):
    """An ebuild directly inherits the same eclass multiple times.

    Note that this will flag ebuilds that conditionalize global metadata by
    package version (or some other fashion) while inheriting the same eclass
    under both branches, e.g. conditional live ebuilds. In this case, shared
    eclasses should be loaded in a separate, unconditional inherit call.
    """

    def __init__(self, eclass, **kwargs):
        super().__init__(**kwargs)
        self.eclass = eclass

    @property
    def desc(self):
        return f"duplicate eclass inherit {self.eclass!r}, line {self.lineno}"


class MisplacedEclassVar(results.LineResult, results.Error):
    """Invalid placement of pre-inherit eclass variable in an ebuild.

    All eclass variables tagged with @PRE_INHERIT must be set
    before the first inherit call in an ebuild.
    """

    def __init__(self, variable, **kwargs):
        super().__init__(**kwargs)
        self.variable = variable

    @property
    def desc(self):
        return f"invalid pre-inherit placement, line {self.lineno}: {self.line!r}"


class ProvidedEclassInherit(results.LineResult, results.Style):
    """Ebuild inherits an eclass which is already provided by another eclass.

    When inheriting an eclass which declares ``@PROVIDES``, those referenced
    eclasses are guaranteed to be provided by the eclass. Therefore, inheriting
    them in ebuilds is redundant and should be removed.
    """

    def __init__(self, provider, **kwargs):
        super().__init__(**kwargs)
        self.provider = provider

    @property
    def desc(self):
        return f"line {self.lineno}: redundant eclass inherit {self.line!r}, provided by {self.provider!r}"


class EclassUsageCheck(Check):
    """Scan packages for various eclass-related issues."""

    _source = sources.EbuildParseRepoSource
    known_results = frozenset(
        {
            DeprecatedEclass,
            DeprecatedEclassVariable,
            DeprecatedEclassFunction,
            DuplicateEclassInherit,
            EclassUserVariableUsage,
            MisplacedEclassVar,
            ProvidedEclassInherit,
        }
    )
    required_addons = (addons.eclass.EclassAddon,)

    def __init__(self, *args, eclass_addon):
        super().__init__(*args)
        self.deprecated_eclasses = eclass_addon.deprecated
        self.eclass_cache = eclass_addon.eclasses

    def check_pre_inherits(self, pkg, inherits: list[tuple[list[str], int]]):
        """Check for invalid @PRE_INHERIT variable placement."""
        # determine if any inherited eclasses have @PRE_INHERIT variables
        pre_inherits = {
            var.name: lineno
            for eclasses, lineno in inherits
            for eclass in eclasses
            for var in self.eclass_cache[eclass].variables
            if var.pre_inherit
        }

        # scan for any misplaced @PRE_INHERIT variables
        if pre_inherits:
            for node in bash.var_assign_query.captures(pkg.tree.root_node).get("assign", ()):
                var_name = pkg.node_str(node.child_by_field_name("name"))
                lineno, _colno = node.start_point
                if var_name in pre_inherits and lineno > pre_inherits[var_name]:
                    line = pkg.node_str(node)
                    yield MisplacedEclassVar(var_name, line=line, lineno=lineno + 1, pkg=pkg)

    def check_user_variables(self, pkg: bash.ParseTree, inherits: list[tuple[list[str], int]]):
        """Check for usage of @USER_VARIABLE variables."""
        # determine if any inherited eclasses have @USER_VARIABLE variables
        user_variables = {
            var.name: eclass
            for eclasses, _ in inherits
            for eclass in eclasses
            for var in self.eclass_cache[eclass].variables
            if var.user_variable
        }

        # scan for usage of @USER_VARIABLE variables
        if user_variables:
            for node in bash.var_assign_query.captures(pkg.tree.root_node).get("assign", ()):
                var_name = pkg.node_str(node.child_by_field_name("name"))
                if var_name in user_variables:
                    lineno, _colno = node.start_point
                    yield EclassUserVariableUsage(
                        user_variables[var_name], line=var_name, lineno=lineno + 1, pkg=pkg
                    )

    def check_deprecated_variables(self, pkg, inherits: list[tuple[list[str], int]]):
        """Check for usage of @DEPRECATED variables."""
        # determine if any inherited eclasses have @DEPRECATED variables
        deprecated = {
            var.name: var.deprecated
            for eclasses, _ in inherits
            for eclass in eclasses
            for var in self.eclass_cache[eclass].variables
            if var.deprecated
        }

        # scan for usage of @DEPRECATED variables
        if deprecated:
            for node in bash.var_query.captures(pkg.tree.root_node).get("var", ()):
                var_name = pkg.node_str(node)
                if var_name in deprecated:
                    lineno, _colno = node.start_point
                    line = pkg.node_str(node)
                    replacement = deprecated[var_name]
                    if not isinstance(replacement, str):
                        replacement = None
                    yield DeprecatedEclassVariable(
                        var_name, replacement, line=line, lineno=lineno + 1, pkg=pkg
                    )

    def check_deprecated_functions(self, pkg, inherits: list[tuple[list[str], int]]):
        """Check for usage of @DEPRECATED functions."""
        # determine if any inherited eclasses have @DEPRECATED functions
        deprecated = {
            func.name: func.deprecated
            for eclasses, _ in inherits
            for eclass in eclasses
            for func in self.eclass_cache[eclass].functions
            if func.deprecated
        }

        # scan for usage of @DEPRECATED functions
        if deprecated:
            for node in bash.cmd_query.captures(pkg.tree.root_node).get("call", ()):
                func_name = pkg.node_str(node.child_by_field_name("name"))
                if func_name in deprecated:
                    lineno, _colno = node.start_point
                    line = pkg.node_str(node)
                    replacement = deprecated[func_name]
                    if not isinstance(replacement, str):
                        replacement = None
                    yield DeprecatedEclassFunction(
                        func_name, replacement, line=line, lineno=lineno + 1, pkg=pkg
                    )

    def check_provided_eclasses(self, pkg, inherits: list[tuple[list[str], int]]):
        """Check for usage of eclasses (i.e. redundant inherits) that are
        provided by another inherited eclass."""
        provided_eclasses = {
            provided: (eclass, lineno + 1)
            for eclasses, lineno in inherits
            for eclass in eclasses
            for provided in pkg.inherit.intersection(self.eclass_cache[eclass].provides)
        }
        for provided, (eclass, lineno) in provided_eclasses.items():
            yield ProvidedEclassInherit(eclass, pkg=pkg, line=provided, lineno=lineno)

    def feed(self, pkg):
        if pkg.inherit:
            inherited: set[str] = set()
            inherits: list[tuple[list[str], int]] = []
            for node in bash.cmd_query.captures(pkg.tree.root_node).get("call", ()):
                name = pkg.node_str(node.child_by_field_name("name"))
                if name == "inherit":
                    call = pkg.node_str(node)
                    # filter out line continuations and conditional inherits
                    if eclasses := [x for x in call.split()[1:] if x in pkg.inherit]:
                        lineno, _colno = node.start_point
                        if not inherited and eclasses[0] == pkg.inherit[0]:
                            inherits.append((eclasses, lineno))

                        for eclass in eclasses:
                            if eclass not in inherited:
                                inherited.add(eclass)
                            else:
                                yield DuplicateEclassInherit(
                                    eclass, line=call, lineno=lineno + 1, pkg=pkg
                                )

            yield from self.check_provided_eclasses(pkg, inherits)
            yield from self.check_user_variables(pkg, inherits)
            # verify @PRE_INHERIT variable placement
            yield from self.check_pre_inherits(pkg, inherits)
            # verify @DEPRECATED variables or functions
            yield from self.check_deprecated_variables(pkg, inherits)
            yield from self.check_deprecated_functions(pkg, inherits)

            for eclass in pkg.inherit.intersection(self.deprecated_eclasses):
                replacement = self.deprecated_eclasses[eclass]
                if not isinstance(replacement, str):
                    replacement = None
                yield DeprecatedEclass(eclass, replacement, pkg=pkg)


class EclassVariableScope(VariableScope, results.EclassResult):
    """Eclass using variable outside its defined scope."""

    @property
    def desc(self):
        return f"{self.eclass}: {super().desc}"


class EclassExportFuncsBeforeInherit(results.EclassResult, results.Error):
    """EXPORT_FUNCTIONS called before inherit.

    The EXPORT_FUNCTIONS call should occur after all inherits are done in order
    to guarantee consistent behavior across all package managers.
    """

    def __init__(self, export_line, inherit_line, **kwargs):
        super().__init__(**kwargs)
        self.export_line = export_line
        self.inherit_line = inherit_line

    @property
    def desc(self):
        return (
            f"{self.eclass}: EXPORT_FUNCTIONS (line {self.export_line}) called before inherit (line "
            f"{self.inherit_line})"
        )


class EclassParseCheck(Check):
    """Scan eclasses variables that are only allowed in certain scopes."""

    _source = sources.EclassParseRepoSource
    known_results = frozenset([EclassVariableScope, EclassExportFuncsBeforeInherit])
    required_addons = (addons.eclass.EclassAddon,)

    def __init__(self, *args, eclass_addon):
        super().__init__(*args)
        self.eclass_cache = eclass_addon.eclasses

    def eclass_phase_vars(self, eclass, phase):
        """Return set of bad variables for a given eclass and potential phase function."""
        eapis = map(EAPI.known_eapis.get, self.eclass_cache[eclass.name].supported_eapis)
        if not eapis:
            eapis = EAPI.known_eapis.values()
        variables = set()
        for eapi in eapis:
            variables.update(VariableScopeCheck.scoped_vars[eapi].get(phase, ()))
        return variables

    def feed(self, eclass):
        func_prefix = f"{eclass.name}_"
        for func_node in bash.func_query.captures(eclass.tree.root_node).get("func", ()):
            func_name = eclass.node_str(func_node.child_by_field_name("name"))
            if not func_name.startswith(func_prefix):
                continue
            phase = func_name[len(func_prefix) :]
            if variables := self.eclass_phase_vars(eclass, phase):
                usage = defaultdict(set)
                for var_node in bash.var_query.captures(func_node).get("var", ()):
                    var_name = eclass.node_str(var_node)
                    if var_name in variables:
                        lineno, _colno = var_node.start_point
                        usage[var_name].add(lineno + 1)
                for var, lines in sorted(usage.items()):
                    yield EclassVariableScope(
                        var, func_name, lines=sorted(lines), eclass=eclass.name
                    )

        export_funcs_called = None
        for node in eclass.global_query(bash.cmd_query):
            call = eclass.node_str(node)
            if call.startswith("EXPORT_FUNCTIONS"):
                export_funcs_called = node.start_point[0] + 1
            elif call.startswith("inherit"):
                if export_funcs_called is not None:
                    yield EclassExportFuncsBeforeInherit(
                        export_funcs_called, node.start_point[0] + 1, eclass=eclass.name
                    )
                    break


class EclassBashSyntaxError(results.EclassResult, results.Error):
    """Bash syntax error in the related eclass."""

    def __init__(self, lineno, error, **kwargs):
        super().__init__(**kwargs)
        self.lineno = lineno
        self.error = error

    @property
    def desc(self):
        return f"{self.eclass}: bash syntax error, line {self.lineno}: {self.error}"


class EclassDocError(results.EclassResult, results.Warning):
    """Error when parsing docs for the related eclass.

    Eclass docs are parsed as specified by the devmanual [#]_.

    .. [#] https://devmanual.gentoo.org/eclass-writing/#documenting-eclasses
    """

    def __init__(self, error, **kwargs):
        super().__init__(**kwargs)
        self.error = error

    @property
    def desc(self):
        return f"{self.eclass}: failed parsing eclass docs: {self.error}"


class EclassDocMissingFunc(results.EclassResult, results.Warning):
    """Undocumented function(s) in the related eclass."""

    def __init__(self, functions, **kwargs):
        super().__init__(**kwargs)
        self.functions = tuple(functions)

    @property
    def desc(self):
        s = pluralism(self.functions)
        funcs = ", ".join(self.functions)
        return f"{self.eclass}: undocumented function{s}: {funcs}"


class EclassDocMissingVar(results.EclassResult, results.Warning):
    """Undocumented variable(s) in the related eclass.

    All exported variables in an eclass should be documented using eclass doc
    tags. Temporary variables should be unset after use so they aren't
    exported.
    """

    def __init__(self, variables, **kwargs):
        super().__init__(**kwargs)
        self.variables = tuple(variables)

    @property
    def desc(self):
        s = pluralism(self.variables)
        variables = ", ".join(self.variables)
        return f"{self.eclass}: undocumented variable{s}: {variables}"


class EclassCheck(Check):
    """Scan eclasses for various issues."""

    _source = sources.EclassRepoSource
    known_results = frozenset(
        [
            EclassBashSyntaxError,
            EclassDocError,
            EclassDocMissingFunc,
            EclassDocMissingVar,
        ]
    )

    def __init__(self, *args):
        super().__init__(*args)
        latest_eapi = EAPI.known_eapis[sorted(EAPI.known_eapis)[-1]]
        # all known build phases, e.g. src_configure
        self.known_phases = list(latest_eapi.phases_rev)
        # metadata variables allowed to be set in eclasses, e.g. SRC_URI
        self.eclass_keys = latest_eapi.eclass_keys

    def feed(self, eclass):
        # check for eclass bash syntax errors
        p = subprocess.run(
            ["bash", "-n", shlex.quote(eclass.path)],
            stderr=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            env={"LC_ALL": "C"},
            encoding="utf8",
        )
        if p.returncode != 0 and p.stderr:
            lineno = 0
            error = []
            for line in p.stderr.splitlines():
                _path, line, msg = line.split(": ", 2)
                lineno = line[5:]
                error.append(msg.strip("\n"))
            error = ": ".join(error)
            yield EclassBashSyntaxError(lineno, error, eclass=eclass)

        report_logs = (
            LogMap("pkgcore.log.logger.error", partial(EclassDocError, eclass=eclass)),
            LogMap("pkgcore.log.logger.warning", partial(EclassDocError, eclass=eclass)),
        )

        with LogReports(*report_logs) as log_reports:
            eclass_obj = EclassDoc(eclass.path, sourced=True)
        yield from log_reports

        phase_funcs = {f"{eclass}_{phase}" for phase in self.known_phases}
        funcs_missing_docs = (
            eclass_obj.exported_function_names - phase_funcs - eclass_obj.function_names
        )
        if funcs_missing_docs:
            yield EclassDocMissingFunc(sorted(funcs_missing_docs), eclass=eclass)
        # ignore underscore-prefixed vars (mostly used for avoiding multiple inherits)
        exported_vars = {x for x in eclass_obj.exported_variable_names if not x.startswith("_")}
        vars_missing_docs = (
            exported_vars
            - self.eclass_keys
            - eclass_obj.variable_names
            - eclass_obj.function_variable_names
        )
        if vars_missing_docs:
            yield EclassDocMissingVar(sorted(vars_missing_docs), eclass=eclass)


class GoMissingDeps(results.VersionResult, results.Warning):
    """Package sets ``GO_OPTIONAL`` but does not depend on ``dev-lang/go``."""

    desc = "sets GO_OPTIONAL but does not depend on dev-lang/go"


class RubyMissingDeps(results.VersionResult, results.Warning):
    """Package sets ``RUBY_OPTIONAL`` but does not depend on ``dev-lang/ruby``
    or ``virtual/rubygems``."""

    desc = "sets RUBY_OPTIONAL but does not depend on dev-lang/ruby or virtual/rubygems"


class RustMissingDeps(results.VersionResult, results.Warning):
    """Package sets ``RUST_OPTIONAL`` but does not use ``${RUST_DEPEND}``."""

    desc = "sets RUST_OPTIONAL (or CARGO_OPTIONAL) but does not use ${RUST_DEPEND}"


class TmpfilesMissingDeps(results.VersionResult, results.Warning):
    """Package sets ``TMPFILES_OPTIONAL`` but does not depend on ``virtual/tmpfiles``."""

    desc = "sets TMPFILES_OPTIONAL but does not depend on virtual/tmpfiles"


class EclassManualDepsCheck(Check):
    """Check for missing deps when inheriting eclasses in special mode."""

    _source = sources.EbuildParseRepoSource
    known_results = frozenset(
        {
            GoMissingDeps,
            RustMissingDeps,
            RubyMissingDeps,
            TmpfilesMissingDeps,
        }
    )

    dependencies = (
        # eclass, variable, one of deps, class
        ("cargo", "CARGO_OPTIONAL", {"dev-lang/rust", "dev-lang/rust-bin"}, RustMissingDeps),
        ("rust", "RUST_OPTIONAL", {"dev-lang/rust", "dev-lang/rust-bin"}, RustMissingDeps),
        ("go-module", "GO_OPTIONAL", {"dev-lang/go"}, GoMissingDeps),
        (
            "ruby-ng",
            "RUBY_OPTIONAL",
            {"dev-lang/ruby", "virtual/rubygems", "dev-ruby"},
            RubyMissingDeps,
        ),
        ("tmpfiles", "TMPFILES_OPTIONAL", {"virtual/tmpfiles"}, TmpfilesMissingDeps),
    )

    def __init__(self, options, **kwargs):
        super().__init__(options, **kwargs)

        self.queries_by_eclass = defaultdict(list)
        for eclass, variable, deps, cls in self.dependencies:
            pkgs = frozenset({x for x in deps if "/" in x})
            categories = frozenset({x for x in deps if "/" not in x})
            self.queries_by_eclass[eclass].append(
                (
                    bash.query(
                        # has variable assignment to a variable named
                        f'(variable_assignment name: (variable_name) @name (.eq? @name "{variable}"))'
                    ),
                    pkgs,
                    categories,
                    cls,
                )
            )

    def feed(self, pkg: bash.ParseTree):
        for eclass, queries in self.queries_by_eclass.items():
            if eclass not in pkg.inherited:
                continue
            for query, pkgs, categories, cls in queries:
                # is the variable assigned in global scope
                try:
                    next(pkg.global_query(query))
                except StopIteration:
                    continue

                # does any dep attr have any of the deps
                if all(
                    atom.key not in pkgs and atom.category not in categories
                    for attr in pkg.eapi.dep_keys
                    for atom in iflatten_instance(getattr(pkg, attr.lower()), atom_cls)
                ):
                    yield cls(pkg)
