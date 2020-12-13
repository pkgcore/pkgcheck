import shlex
import subprocess

from pkgcore.ebuild.eapi import EAPI
from pkgcore.ebuild.eclass import EclassDoc
from snakeoil.contexts import patch
from snakeoil.strings import pluralism

from .. import addons, base, results, sources
from ..eclass import EclassAddon
from . import Check, EclassCacheCheck


class DeprecatedEclass(results.VersionResult, results.Warning):
    """Package uses an eclass that is deprecated/abandoned."""

    def __init__(self, eclass, replacement, **kwargs):
        super().__init__(**kwargs)
        self.eclass = eclass
        self.replacement = replacement

    @property
    def desc(self):
        if self.replacement is not None:
            replacement = f'migrate to {self.replacement}'
        else:
            replacement = 'no replacement'
        return f'uses deprecated eclass: {self.eclass} ({replacement})'


class DuplicateEclassInherits(results.VersionResult, results.Warning):
    """An ebuild directly inherits the same eclass multiple times.

    Note that this will flag ebuilds that conditionalize global metadata by
    package version (or some other fashion) while inheriting the same eclass
    under both branches, e.g. conditional live ebuilds. In this case, shared
    eclasses should be loaded in a separate, unconditional inherit call.
    """

    def __init__(self, eclasses, **kwargs):
        super().__init__(**kwargs)
        self.eclasses = tuple(eclasses)

    @property
    def desc(self):
        eclasses = ', '.join(self.eclasses)
        es = pluralism(self.eclasses, plural='es')
        return f'duplicate inherits for eclass{es}: {eclasses}'


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
        return f'invalid pre-inherit placement, line {self.lineno}: {self.line!r}'


class EclassUsageCheck(Check):
    """Scan packages for various eclass-related issues."""

    _source = sources.EbuildParseRepoSource
    known_results = frozenset([
        DeprecatedEclass, DuplicateEclassInherits, MisplacedEclassVar,
    ])
    required_addons = (addons.BashAddon, EclassAddon)

    def __init__(self, *args, bash_addon, eclass_addon):
        super().__init__(*args)
        self.deprecated_eclasses = eclass_addon.deprecated
        self.eclass_cache = eclass_addon.eclasses
        self.cmd_query = bash_addon.query('(command_name) @command')
        self.var_assign_query = bash_addon.query('(variable_assignment) @assign')

    def feed(self, pkg):
        pre_inherits = set()
        for eclass in pkg.inherited:
            pre_inherits.update(
                var.name for var in self.eclass_cache[eclass].variables
                if var.pre_inherit
            )

        # check for invalid @PRE_INHERIT variable placement
        if pre_inherits:
            for cmd_node, _ in self.cmd_query.captures(pkg.tree.root_node):
                cmd_name = pkg.node_str(cmd_node)
                if cmd_name == 'inherit':
                    inherit_line = cmd_node.start_point[0]
                    for node, _ in self.var_assign_query.captures(pkg.tree.root_node):
                        var_name = pkg.node_str(node.child_by_field_name('name'))
                        lineno = node.start_point[0]
                        if var_name in pre_inherits and lineno > inherit_line:
                            line = pkg.node_str(node)
                            yield MisplacedEclassVar(
                                var_name, line=line, lineno=lineno+1, pkg=pkg)
                    break

        duplicates = set()
        inherited = set()
        for eclass in pkg.inherit:
            if eclass not in inherited:
                inherited.add(eclass)
            else:
                duplicates.add(eclass)

        if duplicates:
            yield DuplicateEclassInherits(sorted(duplicates), pkg=pkg)

        for eclass in inherited.intersection(self.deprecated_eclasses):
            replacement = self.deprecated_eclasses[eclass]
            if not isinstance(replacement, str):
                replacement = None
            yield DeprecatedEclass(eclass, replacement, pkg=pkg)


class EclassBashSyntaxError(results.EclassResult, results.Error):
    """Bash syntax error in the related eclass."""

    def __init__(self, lineno, error, **kwargs):
        super().__init__(**kwargs)
        self.lineno = lineno
        self.error = error

    @property
    def desc(self):
        return f'{self.eclass}: bash syntax error, line {self.lineno}: {self.error}'


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
        return f'{self.eclass}: failed parsing eclass docs: {self.error}'


class EclassDocMissingFunc(results.EclassResult, results.Warning):
    """Undocumented function(s) in the related eclass."""

    def __init__(self, functions, **kwargs):
        super().__init__(**kwargs)
        self.functions = tuple(functions)

    @property
    def desc(self):
        s = pluralism(self.functions)
        funcs = ', '.join(self.functions)
        return f'{self.eclass}: undocumented function{s}: {funcs}'


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
        variables = ', '.join(self.variables)
        return f'{self.eclass}: undocumented variable{s}: {variables}'


class EclassCheck(EclassCacheCheck):
    """Scan eclasses for various issues."""

    scope = base.eclass_scope
    _source = sources.EclassRepoSource
    known_results = frozenset([
        EclassBashSyntaxError, EclassDocError, EclassDocMissingFunc, EclassDocMissingVar])

    def __init__(self, *args):
        super().__init__(*args)
        latest_eapi = EAPI.known_eapis[sorted(EAPI.known_eapis)[-1]]
        self.known_phases = set(latest_eapi.phases_rev)
        self.eclass_keys = latest_eapi.eclass_keys

    def feed(self, eclass):
        # check for eclass bash syntax errors
        p = subprocess.run(
            ['bash', '-n', shlex.quote(eclass.path)],
            stderr=subprocess.PIPE, stdout=subprocess.DEVNULL, encoding='utf8')
        if p.returncode != 0 and p.stderr:
            lineno = 0
            error = []
            for line in p.stderr.splitlines():
                path, line, msg = line.split(': ', 2)
                lineno = line[5:]
                error.append(msg.strip('\n'))
            error = ': '.join(error)
            yield EclassBashSyntaxError(lineno, error, eclass=eclass)

        doc_errors = []
        parsing_error = lambda exc: doc_errors.append(EclassDocError(str(exc), eclass=eclass))
        with patch('pkgcore.ebuild.eclass._parsing_error', parsing_error):
            eclass_obj = EclassDoc(eclass.path, sourced=True)
        yield from doc_errors

        phase_funcs = {f'{eclass}_{phase}' for phase in self.known_phases}
        # TODO: ignore overridden funcs from other eclasses?
        # ignore phase funcs
        funcs_missing_docs = (
            eclass_obj.exported_function_names - phase_funcs - eclass_obj.function_names)
        if funcs_missing_docs:
            missing = tuple(sorted(funcs_missing_docs))
            yield EclassDocMissingFunc(missing, eclass=eclass)
        # TODO: ignore overridden vars from other eclasses?
        # ignore exported metadata variables, e.g. SRC_URI
        vars_missing_docs = (
            eclass_obj.exported_variable_names - eclass_obj.variable_names - self.eclass_keys)
        if vars_missing_docs:
            missing = tuple(sorted(vars_missing_docs))
            yield EclassDocMissingVar(missing, eclass=eclass)
