import shlex
import subprocess
from functools import partial

from pkgcore.ebuild.eapi import EAPI
from pkgcore.ebuild.eclass import EclassDoc
from snakeoil.strings import pluralism

from .. import addons, results, sources
from ..base import LogMap, LogReports
from . import Check


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
        return f'duplicate eclass inherit {self.eclass!r}, line {self.lineno}'


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
        DeprecatedEclass, DuplicateEclassInherit, MisplacedEclassVar,
    ])
    required_addons = (addons.BashAddon, addons.eclass.EclassAddon)

    def __init__(self, *args, bash_addon, eclass_addon):
        super().__init__(*args)
        self.deprecated_eclasses = eclass_addon.deprecated
        self.eclass_cache = eclass_addon.eclasses
        self.cmd_query = bash_addon.query('(command) @call')
        self.var_assign_query = bash_addon.query('(variable_assignment) @assign')

    def check_pre_inherits(self, pkg, inherit_lineno):
        """Check for invalid @PRE_INHERIT variable placement."""
        pre_inherits = set()

        # determine if any inherited eclasses have @PRE_INHERIT variables
        for eclass in pkg.inherited:
            pre_inherits.update(
                var.name for var in self.eclass_cache[eclass].variables
                if var.pre_inherit
            )

        # scan for any misplaced @PRE_INHERIT variables
        if pre_inherits:
            for node, _ in self.var_assign_query.captures(pkg.tree.root_node):
                var_name = pkg.node_str(node.child_by_field_name('name'))
                lineno, _colno = node.start_point
                if var_name in pre_inherits and lineno > inherit_lineno:
                    line = pkg.node_str(node)
                    yield MisplacedEclassVar(
                        var_name, line=line, lineno=lineno+1, pkg=pkg)

    def feed(self, pkg):
        if pkg.inherit:
            inherited = set()
            for node, _ in self.cmd_query.captures(pkg.tree.root_node):
                name = pkg.node_str(node.child_by_field_name('name'))
                if name == 'inherit':
                    call = pkg.node_str(node)
                    # filter out line continuations and conditional inherits
                    if inherits := [x for x in call.split()[1:] if x in pkg.inherit]:
                        lineno, _colno = node.start_point
                        # verify any existing @PRE_INHERIT variable placement
                        if not inherited and inherits[0] == pkg.inherit[0]:
                            yield from self.check_pre_inherits(pkg, lineno)

                        for eclass in inherits:
                            if eclass not in inherited:
                                inherited.add(eclass)
                            else:
                                yield DuplicateEclassInherit(
                                    eclass, line=call, lineno=lineno+1, pkg=pkg)

            for eclass in pkg.inherit.intersection(self.deprecated_eclasses):
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


class EclassCheck(Check):
    """Scan eclasses for various issues."""

    _source = sources.EclassRepoSource
    known_results = frozenset([
        EclassBashSyntaxError, EclassDocError, EclassDocMissingFunc, EclassDocMissingVar])

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
            ['bash', '-n', shlex.quote(eclass.path)],
            stderr=subprocess.PIPE, stdout=subprocess.DEVNULL,
            env={'LC_ALL': 'C'}, encoding='utf8')
        if p.returncode != 0 and p.stderr:
            lineno = 0
            error = []
            for line in p.stderr.splitlines():
                path, line, msg = line.split(': ', 2)
                lineno = line[5:]
                error.append(msg.strip('\n'))
            error = ': '.join(error)
            yield EclassBashSyntaxError(lineno, error, eclass=eclass)

        report_logs = (
            LogMap('pkgcore.log.logger.error', partial(EclassDocError, eclass=eclass)),
            LogMap('pkgcore.log.logger.warning', partial(EclassDocError, eclass=eclass)),
        )

        with LogReports(*report_logs) as log_reports:
            eclass_obj = EclassDoc(eclass.path, sourced=True)
        yield from log_reports

        phase_funcs = {f'{eclass}_{phase}' for phase in self.known_phases}
        funcs_missing_docs = (
            eclass_obj.exported_function_names - phase_funcs - eclass_obj.function_names)
        if funcs_missing_docs:
            yield EclassDocMissingFunc(sorted(funcs_missing_docs), eclass=eclass)
        # ignore underscore-prefixed vars (mostly used for avoiding multiple inherits)
        exported_vars = {x for x in eclass_obj.exported_variable_names if not x.startswith('_')}
        vars_missing_docs = (
            exported_vars - self.eclass_keys
            - eclass_obj.variable_names - eclass_obj.function_variable_names)
        if vars_missing_docs:
            yield EclassDocMissingVar(sorted(vars_missing_docs), eclass=eclass)
