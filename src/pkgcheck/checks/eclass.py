import shlex
import subprocess

from pkgcore.ebuild.eapi import EAPI
from snakeoil.contexts import patch
from snakeoil.process.spawn import spawn_get_output
from snakeoil.strings import pluralism

from .. import base, results, sources
from ..eclass import Eclass, EclassAddon
from . import Check


class DeprecatedEclass(results.VersionResult, results.Warning):
    """Package uses an eclass that is deprecated/abandoned."""

    def __init__(self, eclasses, **kwargs):
        super().__init__(**kwargs)
        self.eclasses = tuple(eclasses)

    @property
    def desc(self):
        eclass_migration = []
        for old_eclass, new_eclass in self.eclasses:
            if new_eclass:
                update_path = f'migrate to {new_eclass}'
            else:
                update_path = 'no replacement'
            eclass_migration.append(f'{old_eclass} ({update_path})')

        es = pluralism(eclass_migration, plural='es')
        eclasses = ', '.join(eclass_migration)
        return f'uses deprecated eclass{es}: [ {eclasses} ]'


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


class EclassUsageCheck(Check):
    """Scan packages for various eclass-related issues."""

    known_results = frozenset([DeprecatedEclass, DuplicateEclassInherits])
    required_addons = (EclassAddon,)

    def __init__(self, *args, eclass_addon):
        super().__init__(*args)
        self.eclass_addon = eclass_addon

    def feed(self, pkg):
        deprecated = []
        duplicates = set()
        inherited = set()

        for eclass in pkg.inherit:
            if eclass not in inherited:
                inherited.add(eclass)
            else:
                duplicates.add(eclass)

        for eclass in inherited.intersection(self.eclass_addon.deprecated):
            replacement = self.eclass_addon.deprecated[eclass]
            deprecated.append((eclass, replacement))

        if duplicates:
            yield DuplicateEclassInherits(sorted(duplicates), pkg=pkg)
        if deprecated:
            yield DeprecatedEclass(sorted(deprecated), pkg=pkg)


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
        self.functions = functions

    @property
    def desc(self):
        s = pluralism(self.functions)
        funcs = ', '.join(self.functions)
        return f'{self.eclass}: undocumented function{s}: {funcs}'


class EclassCheck(Check):
    """Scan eclasses for various issues."""

    scope = base.eclass_scope
    _source = sources.EclassRepoSource
    known_results = frozenset([
        EclassBashSyntaxError, EclassDocError, EclassDocMissingFunc])

    def __init__(self, *args):
        super().__init__(*args)
        latest_eapi = sorted(EAPI.known_eapis)[-1]
        self.known_phases = set(EAPI.known_eapis[latest_eapi].phases_rev)

    def feed(self, eclass):
        # check for eclass bash syntax errors
        ret, err = spawn_get_output(['bash', '-n', eclass.path], collect_fds=(2,))
        if ret != 0 and err:
            lineno = 0
            error = []
            for line in err:
                path, line, msg = line.split(': ', 2)
                lineno = line[5:]
                error.append(msg.strip('\n'))
            error = ': '.join(error)
            yield EclassBashSyntaxError(lineno, error, eclass=eclass)

        # check for eclass doc parsing errors in gentoo repo
        if self.options.gentoo_repo:
            doc_errors = []
            parsing_error = lambda exc: doc_errors.append(EclassDocError(str(exc), eclass=eclass))
            with patch('pkgcheck.eclass._parsing_error', parsing_error):
                eclass_obj = Eclass(eclass.path)
            yield from doc_errors

        p = subprocess.run(
            ['bash', '-c', f'source {shlex.quote(eclass.path)}; compgen -A function'],
            stderr=subprocess.DEVNULL, stdout=subprocess.PIPE, encoding='utf8')
        if p.returncode == 0:
            phase_funcs = {f'{eclass}_{phase}' for phase in self.known_phases}
            functions = set()
            for func in p.stdout.splitlines():
                # TODO: ignore overridden funcs from other eclasses?
                # ignore underscore prefixed funcs, phase funcs
                if not func.startswith('_') and func not in phase_funcs:
                    functions.add(func)
            funcs_missing_docs = functions - eclass_obj.functions
            if funcs_missing_docs:
                missing = tuple(sorted(funcs_missing_docs))
                yield EclassDocMissingFunc(missing, eclass=eclass)
