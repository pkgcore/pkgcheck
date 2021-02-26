"""Various line-based checks."""

import re
from collections import defaultdict

from pkgcore.ebuild.eapi import EAPI
from snakeoil.mappings import ImmutableDict
from snakeoil.sequences import stable_unique
from snakeoil.strings import pluralism

from .. import addons
from .. import results, sources
from . import Check, OptionalCheck

PREFIX_VARIABLES = ('EROOT', 'ED', 'EPREFIX')
PATH_VARIABLES = ('BROOT', 'ROOT', 'D') + PREFIX_VARIABLES


class _CommandResult(results.LineResult):
    """Generic command result."""

    def __init__(self, command, **kwargs):
        super().__init__(**kwargs)
        self.command = command

    @property
    def usage_desc(self):
        return f'{self.command!r}'

    @property
    def desc(self):
        s = f'{self.usage_desc}, used on line {self.lineno}'
        if self.line != self.command:
            s += f': {self.line!r}'
        return s


class _EapiCommandResult(_CommandResult):
    """Generic EAPI command result."""

    _status = None

    def __init__(self, *args, eapi, **kwargs):
        super().__init__(*args, **kwargs)
        self.eapi = str(eapi)

    @property
    def usage_desc(self):
        return f'{self.command!r} {self._status} in EAPI {self.eapi}'


class DeprecatedEapiCommand(_EapiCommandResult, results.Warning):
    """Ebuild uses a deprecated EAPI command."""

    _status = 'deprecated'


class BannedEapiCommand(_EapiCommandResult, results.Error):
    """Ebuild uses a banned EAPI command."""

    _status = 'banned'


class BadCommandsCheck(Check):
    """Scan ebuild for various deprecated and banned command usage."""

    _source = sources.EbuildParseRepoSource
    known_results = frozenset([DeprecatedEapiCommand, BannedEapiCommand])
    required_addons = (addons.BashAddon,)

    def __init__(self, *args, bash_addon):
        super().__init__(*args)
        self.cmd_query = bash_addon.query('(command) @call')

    def feed(self, pkg):
        for node, _ in self.cmd_query.captures(pkg.tree.root_node):
            call = pkg.node_str(node)
            name = pkg.node_str(node.child_by_field_name('name'))
            lineno, colno = node.start_point
            if name in pkg.eapi.bash_cmds_banned:
                yield BannedEapiCommand(name, line=call, lineno=lineno+1, eapi=pkg.eapi, pkg=pkg)
            elif name in pkg.eapi.bash_cmds_deprecated:
                yield DeprecatedEapiCommand(name, line=call, lineno=lineno+1, eapi=pkg.eapi, pkg=pkg)


class MissingSlash(results.VersionResult, results.Error):
    """Ebuild uses a path variable missing a trailing slash."""

    def __init__(self, match, lines, **kwargs):
        super().__init__(**kwargs)
        self.match = match
        self.lines = tuple(lines)

    @property
    def desc(self):
        s = pluralism(self.lines)
        lines = ', '.join(map(str, self.lines))
        return f'{self.match} missing trailing slash on line{s}: {lines}'


class UnnecessarySlashStrip(results.VersionResult, results.Style):
    """Ebuild uses a path variable that strips a nonexistent slash."""

    def __init__(self, match, lines, **kwargs):
        super().__init__(**kwargs)
        self.match = match
        self.lines = tuple(lines)

    @property
    def desc(self):
        s = pluralism(self.lines)
        lines = ', '.join(map(str, self.lines))
        return f'{self.match} unnecessary slash strip on line{s}: {lines}'


class DoublePrefixInPath(results.VersionResult, results.Error):
    """Ebuild uses two consecutive paths including EPREFIX.

    Ebuild combines two path variables (or a variable and a getter), both
    of which include EPREFIX, resulting in double prefixing. This is the case
    when combining many pkg-config-based or alike getters with ED or EROOT.

    For example, ``${ED}$(python_get_sitedir)`` should be replaced
    with ``${D}$(python_get_sitedir)``.
    """

    def __init__(self, match, lines, **kwargs):
        super().__init__(**kwargs)
        self.match = match
        self.lines = tuple(lines)

    @property
    def desc(self):
        s = pluralism(self.lines)
        lines = ', '.join(map(str, self.lines))
        return f'{self.match}: concatenates two paths containing EPREFIX on line{s} {lines}'


class PathVariablesCheck(Check):
    """Scan ebuild for path variables with various issues."""

    _source = sources.EbuildFileRepoSource
    known_results = frozenset([MissingSlash, UnnecessarySlashStrip, DoublePrefixInPath])
    prefixed_dir_functions = (
        'insinto', 'exeinto',
        'dodir', 'keepdir',
        'fowners', 'fperms',
        # java-pkg-2
        'java-pkg_jarinto', 'java-pkg_sointo',
        # python-utils-r1
        'python_scriptinto', 'python_moduleinto',
    )
    # TODO: add variables to mark this status in the eclasses in order to pull
    # this data from parsed eclass docs
    prefixed_getters = (
        # bash-completion-r1.eclass
        'get_bashcompdir', 'get_bashhelpersdir',
        # db-use.eclass
        'db_includedir',
        # golang-base.eclass
        'get_golibdir_gopath',
        # llvm.eclass
        'get_llvm_prefix',
        # python-utils-r1.eclass
        'python_get_sitedir', 'python_get_includedir',
        'python_get_library_path', 'python_get_scriptdir',
        # qmake-utils.eclass
        'qt4_get_bindir', 'qt5_get_bindir',
        # s6.eclass
        's6_get_servicedir',
        # systemd.eclass
        'systemd_get_systemunitdir', 'systemd_get_userunitdir',
        'systemd_get_utildir', 'systemd_get_systemgeneratordir',
    )
    prefixed_rhs_variables = (
        # catch silly ${ED}${EPREFIX} mistake ;-)
        'EPREFIX',
        # python-utils-r1.eclass
        'PYTHON', 'PYTHON_SITEDIR', 'PYTHON_INCLUDEDIR', 'PYTHON_LIBPATH',
        'PYTHON_CONFIG', 'PYTHON_SCRIPTDIR',
    )

    def __init__(self, *args):
        super().__init__(*args)
        self.missing_regex = re.compile(r'(\${(%s)})"?\w+/' % r'|'.join(PATH_VARIABLES))
        self.unnecessary_regex = re.compile(r'(\${(%s)%%/})' % r'|'.join(PATH_VARIABLES))
        self.double_prefix_regex = re.compile(
            r'(\${(%s)(%%/)?}/?\$(\((%s)\)|{(%s)}))' % (
                r'|'.join(PREFIX_VARIABLES),
                r'|'.join(self.prefixed_getters),
                r'|'.join(self.prefixed_rhs_variables)))
        self.double_prefix_func_regex = re.compile(
            r'\b(%s)\s[^&|;]*\$(\((%s)\)|{(%s)})' % (
                r'|'.join(self.prefixed_dir_functions),
                r'|'.join(self.prefixed_getters),
                r'|'.join(self.prefixed_rhs_variables)))
        # do not catch ${foo#${EPREFIX}} and similar
        self.double_prefix_func_false_positive_regex = re.compile(
            r'.*?[#]["]?\$(\((%s)\)|{(%s)})' % (
                r'|'.join(self.prefixed_getters),
                r'|'.join(self.prefixed_rhs_variables)))

    def feed(self, pkg):
        missing = defaultdict(list)
        unnecessary = defaultdict(list)
        double_prefix = defaultdict(list)

        for lineno, line in enumerate(pkg.lines, 1):
            line = line.strip()
            if not line:
                continue

            # flag double path prefix usage on uncommented lines only
            if line[0] != '#':
                if mo := self.double_prefix_regex.search(line):
                    double_prefix[mo.group(1)].append(lineno)
                if mo := self.double_prefix_func_regex.search(line):
                    if not self.double_prefix_func_false_positive_regex.match(mo.group(0)):
                        double_prefix[mo.group(0)].append(lineno)

            # skip EAPIs that don't require trailing slashes
            if pkg.eapi.options.trailing_slash:
                continue
            if mo := self.missing_regex.search(line):
                missing[mo.group(1)].append(lineno)
            if mo := self.unnecessary_regex.search(line):
                unnecessary[mo.group(1)].append(lineno)

        for match, lines in missing.items():
            yield MissingSlash(match, lines, pkg=pkg)
        for match, lines in unnecessary.items():
            yield UnnecessarySlashStrip(match, lines, pkg=pkg)
        for match, lines in double_prefix.items():
            yield DoublePrefixInPath(match, lines, pkg=pkg)


class AbsoluteSymlink(results.LineResult, results.Warning):
    """Ebuild uses dosym with absolute paths instead of relative."""

    def __init__(self, cmd, **kwargs):
        super().__init__(**kwargs)
        self.cmd = cmd

    @property
    def desc(self):
        return f"dosym called with absolute path on line {self.lineno}: {self.cmd}"


class AbsoluteSymlinkCheck(Check):
    """Scan ebuild for dosym absolute path usage instead of relative."""

    _source = sources.EbuildFileRepoSource
    known_results = frozenset([AbsoluteSymlink])

    DIRS = ('bin', 'etc', 'lib', 'opt', 'sbin', 'srv', 'usr', 'var')

    def __init__(self, *args):
        super().__init__(*args)
        dirs = '|'.join(self.DIRS)
        path_vars = '|'.join(PATH_VARIABLES)
        prefixed_regex = rf'"\${{({path_vars})(%/)?}}(?P<cp>")?(?(cp)\S*|.*?")'
        non_prefixed_regex = rf'(?P<op>["\'])?/({dirs})(?(op).*?(?P=op)|\S*)'
        self.regex = re.compile(rf'^\s*(?P<cmd>dosym\s+({prefixed_regex}|{non_prefixed_regex}))')

    def feed(self, pkg):
        for lineno, line in enumerate(pkg.lines, 1):
            if not line.strip():
                continue
            if mo := self.regex.match(line):
                yield AbsoluteSymlink(mo.group('cmd'), line=line, lineno=lineno, pkg=pkg)


class DeprecatedInsinto(results.LineResult, results.Warning):
    """Ebuild uses insinto where more compact commands exist."""

    def __init__(self, cmd, **kwargs):
        super().__init__(**kwargs)
        self.cmd = cmd

    @property
    def desc(self):
        return (
            f'deprecated insinto usage (use {self.cmd} instead), '
            f'line {self.lineno}: {self.line}'
        )


class InsintoCheck(Check):
    """Scan ebuild for deprecated insinto usage."""

    _source = sources.EbuildFileRepoSource
    known_results = frozenset([DeprecatedInsinto])

    path_mapping = ImmutableDict({
        '/etc/conf.d': 'doconfd or newconfd',
        '/etc/env.d': 'doenvd or newenvd',
        '/etc/init.d': 'doinitd or newinitd',
        '/etc/pam.d': 'dopamd or newpamd from pam.eclass',
        '/usr/share/applications': 'domenu or newmenu from desktop.eclass',
    })

    def __init__(self, *args):
        super().__init__(*args)
        paths = '|'.join(s.replace('/', '/+') + '/?' for s in self.path_mapping)
        self._insinto_re = re.compile(
            rf'(?P<insinto>insinto[ \t]+(?P<path>{paths})(?!/\w+))(?:$|[/ \t])')
        self._insinto_doc_re = re.compile(
            r'(?P<insinto>insinto[ \t]+/usr/share/doc/(")?\$\{PF?\}(?(2)\2)(/\w+)*)(?:$|[/ \t])')

    def feed(self, pkg):
        for lineno, line in enumerate(pkg.lines, 1):
            if not line.strip():
                continue
            matches = self._insinto_re.search(line)
            if matches is not None:
                path = re.sub('//+', '/', matches.group('path'))
                cmd = self.path_mapping[path.rstrip('/')]
                yield DeprecatedInsinto(
                    cmd, line=matches.group('insinto'), lineno=lineno, pkg=pkg)
                continue
            # Check for insinto usage that should be replaced with
            # docinto/dodoc [-r] under supported EAPIs.
            if pkg.eapi.options.dodoc_allow_recursive:
                matches = self._insinto_doc_re.search(line)
                if matches is not None:
                    yield DeprecatedInsinto(
                        'docinto/dodoc', line=matches.group('insinto'),
                        lineno=lineno, pkg=pkg)


class ObsoleteUri(results.VersionResult, results.Style):
    """URI used is obsolete.

    The URI used to fetch distfile is obsolete and can be replaced
    by something more modern. Note that the modern replacement usually
    results in different file contents, so you need to rename it (to
    avoid mirror collisions with the old file) and update the ebuild
    (for example, by removing no longer necessary vcs-snapshot.eclass).
    """

    def __init__(self, line, uri, replacement, **kwargs):
        super().__init__(**kwargs)
        self.line = line
        self.uri = uri
        self.replacement = replacement

    @property
    def desc(self):
        return (f"obsolete fetch URI: {self.uri} on line "
                f"{self.line}, should be replaced by: {self.replacement}")


class ObsoleteUriCheck(Check):
    """Scan ebuild for obsolete URIs."""

    _source = sources.EbuildFileRepoSource
    known_results = frozenset([ObsoleteUri])

    REGEXPS = (
        (r'.*\b(?P<uri>(?P<prefix>https?://github\.com/.*?/.*?/)'
         r'(?:tar|zip)ball(?P<ref>\S*))',
         r'\g<prefix>archive\g<ref>.tar.gz'),
        (r'.*\b(?P<uri>(?P<prefix>https?://gitlab\.com/.*?/(?P<pkg>.*?)/)'
         r'repository/archive\.(?P<format>tar|tar\.gz|tar\.bz2|zip)'
         r'\?ref=(?P<ref>\S*))',
         r'\g<prefix>-/archive/\g<ref>/\g<pkg>-\g<ref>.\g<format>'),
    )

    def __init__(self, *args):
        super().__init__(*args)
        self.regexes = []
        for regexp, repl in self.REGEXPS:
            self.regexes.append((re.compile(regexp), repl))

    def feed(self, pkg):
        for lineno, line in enumerate(pkg.lines, 1):
            if not line.strip() or line.startswith('#'):
                continue
            # searching for multiple matches on a single line is too slow
            for regexp, repl in self.regexes:
                if mo := regexp.match(line):
                    uri = mo.group('uri')
                    yield ObsoleteUri(lineno, uri, regexp.sub(repl, uri), pkg=pkg)


class HomepageInSrcUri(results.VersionResult, results.Style):
    """${HOMEPAGE} is referenced in SRC_URI.

    SRC_URI is built on top of ${HOMEPAGE}. This is discouraged since HOMEPAGE
    is multi-valued by design, and is subject to potential changes that should
    not accidentally affect SRC_URI.
    """

    @property
    def desc(self):
        return '${HOMEPAGE} in SRC_URI'


class StaticSrcUri(results.VersionResult, results.Style):
    """SRC_URI contains static value instead of the dynamic equivalent.

    For example, using static text to relate to the package version in SRC_URI
    instead of ${P} or ${PV} where relevant.
    """

    def __init__(self, static_str, **kwargs):
        super().__init__(**kwargs)
        self.static_str = static_str

    @property
    def desc(self):
        return f'{self.static_str!r} in SRC_URI'


class VariableInHomepage(results.VersionResult, results.Style):
    """HOMEPAGE includes a variable.

    The HOMEPAGE ebuild variable entry in the devmanual [#]_ states only raw
    text should be used.

    .. [#] https://devmanual.gentoo.org/ebuild-writing/variables/#ebuild-defined-variables
    """

    def __init__(self, variables, **kwargs):
        super().__init__(**kwargs)
        self.variables = tuple(variables)

    @property
    def desc(self):
        s = pluralism(self.variables)
        variables = ', '.join(self.variables)
        return f'HOMEPAGE includes variable{s}: {variables}'


class RawEbuildCheck(Check):
    """Scan raw ebuild content for various issues."""

    _source = sources.EbuildFileRepoSource
    known_results = frozenset([HomepageInSrcUri, StaticSrcUri, VariableInHomepage])

    def __init__(self, *args):
        super().__init__(*args)
        attr_vars = ('HOMEPAGE', 'SRC_URI')
        self.attr_regex = re.compile(
            r'|'.join(rf'^\s*(?P<{x.lower()}>{x}="[^"]*")' for x in attr_vars), re.MULTILINE)
        self.var_regex = re.compile(r'\${[^}]+}')

    def check_homepage(self, pkg, s):
        matches = self.var_regex.findall(s)
        if matches:
            yield VariableInHomepage(stable_unique(matches), pkg=pkg)

    def check_src_uri(self, pkg, s):
        if '${HOMEPAGE}' in s:
            yield HomepageInSrcUri(pkg=pkg)

        exts = pkg.eapi.archive_exts_regex_pattern
        P = re.escape(pkg.P)
        PV = re.escape(pkg.PV)
        static_src_uri_re = rf'/(?P<static_str>({P}{exts}(?="|\n)|{PV}(?=/)))'
        for match in re.finditer(static_src_uri_re, s):
            static_str = match.group('static_str')
            yield StaticSrcUri(static_str, pkg=pkg)

    def feed(self, pkg):
        for mo in self.attr_regex.finditer(''.join(pkg.lines)):
            attr = mo.lastgroup
            func = getattr(self, f'check_{attr}')
            yield from func(pkg, mo.group(attr))


class MissingInherits(results.VersionResult, results.Warning):
    """Ebuild uses function from eclass that isn't inherited."""

    def __init__(self, eclass, lineno, usage, **kwargs):
        super().__init__(**kwargs)
        self.eclass = eclass
        self.lineno = lineno
        self.usage = usage

    @property
    def desc(self):
        return f'{self.eclass}: missing inherit usage: {repr(self.usage)}, line {self.lineno}'


class IndirectInherits(results.VersionResult, results.Warning):
    """Ebuild uses function from indirectly inherited eclass.

    That doesn't allow indirect inherit usage via the @INDIRECT_INHERITS eclass
    doc tag in a parent eclass.
    """

    def __init__(self, eclass, lineno, usage, **kwargs):
        super().__init__(**kwargs)
        self.eclass = eclass
        self.lineno = lineno
        self.usage = usage

    @property
    def desc(self):
        return f'{self.eclass}: indirect inherit usage: {repr(self.usage)}, line {self.lineno}'


class UnusedInherits(results.VersionResult, results.Warning):
    """Ebuild inherits eclasses that are unused."""

    def __init__(self, eclasses, **kwargs):
        super().__init__(**kwargs)
        self.eclasses = tuple(eclasses)

    @property
    def desc(self):
        es = pluralism(self.eclasses, plural='es')
        eclasses = ', '.join(self.eclasses)
        return f'unused eclass{es}: {eclasses}'


class InternalEclassUsage(results.VersionResult, results.Warning):
    """Ebuild uses internal functions or variables from eclass."""

    def __init__(self, eclass, lineno, usage, **kwargs):
        super().__init__(**kwargs)
        self.eclass = eclass
        self.lineno = lineno
        self.usage = usage

    @property
    def desc(self):
        return f'{self.eclass}: internal usage: {repr(self.usage)}, line {self.lineno}'


class InheritsCheck(OptionalCheck):
    """Scan for ebuilds with missing or unused eclass inherits.

    Note that this requires using ``pmaint regen`` to generate repo metadata in
    order for direct inherits to be correct.
    """

    _source = sources.EbuildParseRepoSource
    known_results = frozenset([
        MissingInherits, IndirectInherits, UnusedInherits, InternalEclassUsage])
    required_addons = (addons.BashAddon, addons.eclass.EclassAddon)

    def __init__(self, *args, bash_addon, eclass_addon):
        super().__init__(*args)
        self.eclass_cache = eclass_addon.eclasses
        self.internals = {}
        self.exported = {}

        # register internal and exported funcs/vars for all eclasses
        for eclass, eclass_obj in self.eclass_cache.items():
            self.internals[eclass] = (
                eclass_obj.internal_function_names | eclass_obj.internal_variable_names)
            for name in eclass_obj.exported_function_names:
                self.exported.setdefault(name, set()).add(eclass)
            # Don't use all exported vars in order to avoid
            # erroneously exported temporary loop variables that
            # should be flagged via EclassDocMissingVar.
            for name in eclass_obj.variable_names:
                self.exported.setdefault(name, set()).add(eclass)

        # register EAPI-related funcs/cmds to ignore
        self.eapi_funcs = {}
        for eapi in EAPI.known_eapis.values():
            s = set(eapi.bash_cmds_internal | eapi.bash_cmds_deprecated)
            s.update(
                x for x in (eapi.bash_funcs | eapi.bash_funcs_global)
                if not x.startswith('_'))
            self.eapi_funcs[eapi] = frozenset(s)

        # register EAPI-related vars to ignore
        # TODO: add ebuild env vars via pkgcore setting, e.g. PN, PV, P, FILESDIR, etc
        self.eapi_vars = {}
        for eapi in EAPI.known_eapis.values():
            s = set(eapi.eclass_keys)
            self.eapi_vars[eapi] = frozenset(s)

        # various bash parse tree queries
        self.cmd_query = bash_addon.query('(command) @call')
        self.var_query = bash_addon.query('(variable_name) @var')
        self.var_assign_query = bash_addon.query('(variable_assignment) @assign')

    def get_eclass(self, export, pkg):
        """Return the eclass related to a given exported variable or function name."""
        try:
            eclass = self.exported[export]
        except KeyError:
            # function or variable not exported by any eclass
            return

        # last exporting eclass takes precedence for multiple inheritance
        if len(eclass) > 1:
            if inherited := pkg.inherited.intersection(eclass):
                eclass = (x for x in reversed(pkg.inherited) if x in inherited)
            else:
                return

        return next(iter(eclass))

    def feed(self, pkg):
        conditional = set()

        # register variables assigned in ebuilds
        assigned_vars = dict()
        for node, _ in self.var_assign_query.captures(pkg.tree.root_node):
            name = pkg.node_str(node.child_by_field_name('name'))
            if eclass := self.get_eclass(name, pkg):
                assigned_vars[name] = eclass

        # match captured commands with eclasses
        used = defaultdict(list)
        for node, _ in self.cmd_query.captures(pkg.tree.root_node):
            call = pkg.node_str(node)
            name = pkg.node_str(node.child_by_field_name('name'))
            if name == 'inherit':
                # register conditional eclasses
                eclasses = call.split()[1:]
                if not pkg.inherited.intersection(eclasses):
                    conditional.update(eclasses)
            # Also ignore vars since any used in arithmetic expansions, i.e.
            # $((...)), are captured as commands.
            elif name not in self.eapi_funcs[pkg.eapi] | assigned_vars.keys():
                lineno, colno = node.start_point
                if eclass := self.get_eclass(name, pkg):
                    used[eclass].append((lineno + 1, name, call.split('\n', 1)[0]))

        # match captured variables with eclasses
        for node, _ in self.var_query.captures(pkg.tree.root_node):
            name = pkg.node_str(node)
            if name not in self.eapi_vars[pkg.eapi] | assigned_vars.keys():
                lineno, colno = node.start_point
                if eclass := self.get_eclass(name, pkg):
                    used[eclass].append((lineno + 1, name, name))

        # allowed indirect inherits
        indirect_allowed = set().union(*(
            self.eclass_cache[x].indirect_eclasses for x in pkg.inherit))
        # missing inherits
        missing = used.keys() - pkg.inherit - indirect_allowed - conditional

        unused = set(pkg.inherit) - used.keys() - set(assigned_vars.values())
        # remove eclasses that use implicit phase functions
        if unused and pkg.defined_phases:
            phases = [pkg.eapi.phases[x] for x in pkg.defined_phases]
            for eclass in list(unused):
                if self.eclass_cache[eclass].exported_function_names.intersection(
                        f'{eclass}_{phase}' for phase in phases):
                    unused.discard(eclass)

        for eclass in list(unused):
            if self.eclass_cache[eclass].name is None:
                # ignore eclasses with parsing failures
                unused.discard(eclass)
            else:
                exported_eclass_keys = pkg.eapi.eclass_keys.intersection(
                    self.eclass_cache[eclass].exported_variable_names)
                if not self.eclass_cache[eclass].exported_function_names and exported_eclass_keys:
                    # ignore eclasses that export ebuild metadata (e.g.
                    # SRC_URI, S, ...) and no functions
                    unused.discard(eclass)

        for eclass in pkg.inherited.intersection(used):
            for lineno, name, usage in used[eclass]:
                if name in self.internals[eclass]:
                    yield InternalEclassUsage(eclass, lineno, usage, pkg=pkg)

        for eclass in missing:
            lineno, name, usage = used[eclass][0]
            if eclass in pkg.inherited:
                yield IndirectInherits(eclass, lineno, usage, pkg=pkg)
            elif not self.eclass_cache[eclass].live:
                # try to ignore probable, conditional vcs eclasses
                yield MissingInherits(eclass, lineno, usage, pkg=pkg)

        if unused:
            yield UnusedInherits(sorted(unused), pkg=pkg)


class RedundantDodir(results.LineResult, results.Style):
    """Ebuild using a redundant dodir call."""

    def __init__(self, cmd, **kwargs):
        super().__init__(**kwargs)
        self.cmd = cmd

    @property
    def desc(self):
        return f"dodir called before {self.cmd}, line {self.lineno}: {self.line}"


class RedundantDodirCheck(Check):
    """Scan ebuild for redundant dodir usage."""

    _source = sources.EbuildFileRepoSource
    known_results = frozenset([RedundantDodir])

    def __init__(self, *args):
        super().__init__(*args)
        cmds = r'|'.join(('insinto', 'exeinto', 'docinto'))
        self.cmds_regex = re.compile(rf'^\s*(?P<cmd>({cmds}))\s+(?P<path>\S+)')
        self.dodir_regex = re.compile(r'^\s*(?P<call>dodir\s+(?P<path>\S+))')

    def feed(self, pkg):
        lines = enumerate(pkg.lines, 1)
        for lineno, line in lines:
            line = line.strip()
            if not line or line[0] == '#':
                continue
            if dodir := self.dodir_regex.match(line):
                lineno, line = next(lines)
                if cmd := self.cmds_regex.match(line):
                    if dodir.group('path') == cmd.group('path'):
                        yield RedundantDodir(
                            cmd.group('cmd'), line=dodir.group('call'),
                            lineno=lineno - 1, pkg=pkg)
