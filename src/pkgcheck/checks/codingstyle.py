"""Various line-based checks."""

import re
from collections import defaultdict

from pkgcore.ebuild.eapi import EAPI
from snakeoil.mappings import ImmutableDict
from snakeoil.sequences import stable_unique
from snakeoil.strings import pluralism

from .. import addons, bash
from .. import results, sources
from . import Check

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

    def feed(self, pkg):
        for func_node, _ in bash.func_query.captures(pkg.tree.root_node):
            for node, _ in bash.cmd_query.captures(func_node):
                call = pkg.node_str(node)
                name = pkg.node_str(node.child_by_field_name('name'))
                lineno, colno = node.start_point
                if name in pkg.eapi.bash_cmds_banned:
                    yield BannedEapiCommand(name, line=call, lineno=lineno+1, eapi=pkg.eapi, pkg=pkg)
                elif name in pkg.eapi.bash_cmds_deprecated:
                    yield DeprecatedEapiCommand(name, line=call, lineno=lineno+1, eapi=pkg.eapi, pkg=pkg)


class EendMissingArg(results.LineResult, results.Warning):
    """Ebuild calls eend with no arguments."""

    @property
    def desc(self):
        return f'eend with no arguments, on line {self.lineno}'


class EendMissingArgCheck(Check):
    """Scan an ebuild for calls to eend with no arguments."""

    _source = sources.EbuildParseRepoSource
    known_results = frozenset([EendMissingArg])

    def feed(self, pkg):
        for func_node, _ in bash.func_query.captures(pkg.tree.root_node):
            for node, _ in bash.cmd_query.captures(func_node):
                line = pkg.node_str(node)
                if line == "eend":
                    lineno, _ = node.start_point
                    yield EendMissingArg(line=line, lineno=lineno+1, pkg=pkg)


class MissingSlash(results.LinesResult, results.Error):
    """Ebuild uses a path variable missing a trailing slash."""

    def __init__(self, match, **kwargs):
        super().__init__(**kwargs)
        self.match = match

    @property
    def desc(self):
        return f'{self.match} missing trailing slash {self.lines_str}'


class UnnecessarySlashStrip(results.LinesResult, results.Style):
    """Ebuild uses a path variable that strips a nonexistent slash."""

    def __init__(self, match, **kwargs):
        super().__init__(**kwargs)
        self.match = match

    @property
    def desc(self):
        return f'{self.match} unnecessary slash strip {self.lines_str}'


class DoublePrefixInPath(results.LinesResult, results.Error):
    """Ebuild uses two consecutive paths including EPREFIX.

    Ebuild combines two path variables (or a variable and a getter), both
    of which include EPREFIX, resulting in double prefixing. This is the case
    when combining many pkg-config-based or alike getters with ED or EROOT.

    For example, ``${ED}$(python_get_sitedir)`` should be replaced
    with ``${D}$(python_get_sitedir)``.
    """

    def __init__(self, match, **kwargs):
        super().__init__(**kwargs)
        self.match = match

    @property
    def desc(self):
        return f'{self.match}: concatenates two paths containing EPREFIX {self.lines_str}'


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
            yield MissingSlash(match, lines=lines, pkg=pkg)
        for match, lines in unnecessary.items():
            yield UnnecessarySlashStrip(match, lines=lines, pkg=pkg)
        for match, lines in double_prefix.items():
            yield DoublePrefixInPath(match, lines=lines, pkg=pkg)


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
        self.regexes = tuple((re.compile(regexp), repl) for regexp, repl in self.REGEXPS)

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

    def __init__(self, static_str: str, replacement: str, **kwargs):
        super().__init__(**kwargs)
        self.static_str = static_str
        self.replacement = replacement

    @property
    def desc(self):
        return f'{self.static_str!r} in SRC_URI, replace with {self.replacement}'


class ReferenceInMetadataVar(results.VersionResult, results.Style):
    """Metadata variable limited to raw text includes variable reference.

    The HOMEPAGE ebuild variable entry in the devmanual [#]_ states only raw
    text should be used.

    KEYWORDS must be a simple string with literal content as stated by the QA
    policy guide [#]_.

    LICENSE must specify all license names verbatim, without referring to any
    variables. The only exception is the LICENSE variable itself, ie appending
    is allowed [#]_.

    .. [#] https://devmanual.gentoo.org/ebuild-writing/variables/#ebuild-defined-variables
    .. [#] https://projects.gentoo.org/qa/policy-guide/ebuild-format.html#pg0105
    .. [#] https://projects.gentoo.org/qa/policy-guide/ebuild-format.html#pg0106
    """

    def __init__(self, variable, refs, **kwargs):
        super().__init__(**kwargs)
        self.variable = variable
        self.refs = tuple(refs)

    @property
    def desc(self):
        s = pluralism(self.refs)
        refs = ', '.join(self.refs)
        return f'{self.variable} includes variable{s}: {refs}'


class MultipleKeywordsLines(results.LinesResult, results.Style):
    """KEYWORDS is specified across multiple lines in global scope.

    Due to limitations of ekeyword it's advised to specify KEYWORDS once on a
    single line in global scope [#]_.

    .. [#] https://projects.gentoo.org/qa/policy-guide/ebuild-format.html#pg0105
    """

    @property
    def desc(self):
        return f"KEYWORDS specified {self.lines_str}"


def verify_vars(*variables):
    """Decorator to register raw variable verification methods."""

    class decorator:
        """Decorator with access to the class of a decorated function."""

        def __init__(self, func):
            self.func = func

        def __set_name__(self, owner, name):
            for v in variables:
                owner.known_variables[v] = self.func
            setattr(owner, name, self.func)

    return decorator


class MetadataVarCheck(Check):
    """Scan various globally assigned metadata variables for issues."""

    _source = sources.EbuildParseRepoSource
    known_results = frozenset([
        HomepageInSrcUri, StaticSrcUri, ReferenceInMetadataVar, MultipleKeywordsLines])

    # mapping between registered variables and verification methods
    known_variables = {}

    @verify_vars('HOMEPAGE', 'KEYWORDS')
    def _raw_text(self, var, node, value, pkg):
        matches = []
        for var_node, _ in bash.var_query.captures(node):
            matches.append(pkg.node_str(var_node.parent))
        if matches:
            yield ReferenceInMetadataVar(var, stable_unique(matches), pkg=pkg)

    @verify_vars('LICENSE')
    def _raw_text_license(self, var, node, value, pkg):
        matches = []
        for var_node, _ in bash.var_query.captures(node):
            var_str = pkg.node_str(var_node.parent).strip()
            if var_str in ['$LICENSE', '${LICENSE}']:
                continue  # LICENSE in LICENSE is ok
            matches.append(var_str)
        if matches:
            yield ReferenceInMetadataVar(var, stable_unique(matches), pkg=pkg)

    def build_src_uri_variants_regex(self, pkg):
        p, pv = pkg.P, pkg.PV
        replacements = {
            p: '${P}',
            pv: '${PV}'
        }
        replacements.setdefault(p.capitalize(), "${P^}")
        replacements.setdefault(p.upper(), "${P^^}")

        for value, replacement in tuple(replacements.items()):
            replacements.setdefault(value.replace('.', ''), replacement.replace('}', '//.}'))
            replacements.setdefault(value.replace('.', '_'), replacement.replace('}', '//./_}'))
            replacements.setdefault(value.replace('.', '-'), replacement.replace('}', '//./-}'))

        pos = 0
        positions = [pos := pv.find('.', pos+1) for _ in range(pv.count('.'))]

        for sep in ('', '-', '_'):
            replacements.setdefault(pv.replace('.', sep, 1), f"$(ver_rs 1 {sep!r})")
            for count in range(2, pv.count('.')):
                replacements.setdefault(pv.replace('.', sep, count), f"$(ver_rs 1-{count} {sep!r})")

        for pos, index in enumerate(positions[1:], start=2):
            replacements.setdefault(pv[:index], f"$(ver_cut 1-{pos})")

        replacements = sorted(replacements.items(), key=lambda x: -len(x[0]))

        return tuple(zip(*replacements))[1], '|'.join(
            rf'(?P<r{index}>{re.escape(s)})'
            for index, (s, _) in enumerate(replacements)
        )

    @verify_vars('SRC_URI')
    def _src_uri(self, var, node, value, pkg):
        if '${HOMEPAGE}' in value:
            yield HomepageInSrcUri(pkg=pkg)

        replacements, regex = self.build_src_uri_variants_regex(pkg)
        static_src_uri_re = rf'(?:/|{re.escape(pkg.PN)}[-._]?|->\s*)[v]?(?P<static_str>({regex}))'
        static_urls = {}
        for match in re.finditer(static_src_uri_re, value):
            relevant = {key: value for key, value in match.groupdict().items() if value is not None}
            static_str = relevant.pop('static_str')
            assert len(relevant) == 1
            key = int(tuple(relevant.keys())[0][1:])
            static_urls[static_str] = replacements[key]

        for static_str, replacement in static_urls.items():
            yield StaticSrcUri(static_str, replacement=replacement, pkg=pkg)

    def feed(self, pkg):
        keywords_lines = set()
        for node in pkg.global_query(bash.var_assign_query):
            name = pkg.node_str(node.child_by_field_name('name'))
            if name in self.known_variables:
                # RHS value node should be last
                val_node = node.children[-1]
                val_str = pkg.node_str(val_node)
                if name == 'KEYWORDS':
                    keywords_lines.add(node.start_point[0] + 1)
                    keywords_lines.add(node.end_point[0] + 1)
                yield from self.known_variables[name](self, name, val_node, val_str, pkg)

        if len(keywords_lines) > 1:
            yield MultipleKeywordsLines(sorted(keywords_lines), pkg=pkg)


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


class InheritsCheck(Check):
    """Scan for ebuilds with missing or unused eclass inherits.

    Note that this requires using ``pmaint regen`` to generate repo metadata in
    order for direct inherits to be correct.
    """

    _source = sources.EbuildParseRepoSource
    known_results = frozenset([
        MissingInherits, IndirectInherits, UnusedInherits, InternalEclassUsage])
    required_addons = (addons.eclass.EclassAddon,)

    def __init__(self, *args, eclass_addon):
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
        for node, _ in bash.var_assign_query.captures(pkg.tree.root_node):
            name = pkg.node_str(node.child_by_field_name('name'))
            if eclass := self.get_eclass(name, pkg):
                assigned_vars[name] = eclass

        # match captured commands with eclasses
        used = defaultdict(list)
        for node, _ in bash.cmd_query.captures(pkg.tree.root_node):
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
        for node, _ in bash.var_query.captures(pkg.tree.root_node):
            name = pkg.node_str(node)
            if node.parent.type == 'unset_command':
                continue
            if name not in self.eapi_vars[pkg.eapi] | assigned_vars.keys():
                lineno, colno = node.start_point
                if eclass := self.get_eclass(name, pkg):
                    used[eclass].append((lineno + 1, name, name))

        # allowed indirect inherits
        indirect_allowed = set().union(*(self.eclass_cache[x].provides for x in pkg.inherit))
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


class ReadonlyVariable(results.LineResult, results.Warning):
    """Ebuild globally assigning value to a readonly variable."""

    def __init__(self, variable, **kwargs):
        super().__init__(**kwargs)
        self.variable = variable

    @property
    def desc(self):
        return f"read-only variable {self.variable!r} assigned, line {self.lineno}: {self.line}"


class ReadonlyVariableCheck(Check):
    """Scan for read-only variables that are globally assigned in an ebuild."""

    _source = sources.EbuildParseRepoSource
    known_results = frozenset([ReadonlyVariable])

    # https://devmanual.gentoo.org/ebuild-writing/variables/#predefined-read-only-variables
    readonly_vars = frozenset([
        'P', 'PN', 'PV', 'PR', 'PVR', 'PF', 'A', 'CATEGORY', 'FILESDIR', 'WORKDIR',
        'T', 'D', 'HOME', 'ROOT', 'DISTDIR', 'EPREFIX', 'ED', 'EROOT', 'SYSROOT',
        'ESYSROOT', 'BROOT', 'MERGE_TYPE', 'REPLACING_VERSIONS', 'REPLACED_BY_VERSION',
    ])

    def feed(self, pkg):
        for node in pkg.global_query(bash.var_assign_query):
            name = pkg.node_str(node.child_by_field_name('name'))
            if name in self.readonly_vars:
                call = pkg.node_str(node)
                lineno, colno = node.start_point
                yield ReadonlyVariable(name, line=call, lineno=lineno + 1, pkg=pkg)


class VariableScope(results.BaseLinesResult, results.AliasResult, results.Warning):
    """Variable used outside its defined scope."""

    _name = 'VariableScope'

    def __init__(self, variable, func, **kwargs):
        super().__init__(**kwargs)
        self.variable = variable
        self.func = func

    @property
    def desc(self):
        return f'variable {self.variable!r} used in {self.func!r} {self.lines_str}'


class EbuildVariableScope(VariableScope, results.VersionResult):
    """Ebuild using variable outside its defined scope."""


class VariableScopeCheck(Check):
    """Scan ebuilds for variables that are only allowed in certain scopes."""

    _source = sources.EbuildParseRepoSource
    known_results = frozenset([EbuildVariableScope])

    # see https://projects.gentoo.org/pms/7/pms.html#x1-10900011.1
    variable_map = ImmutableDict({
        'A': ('src_', 'pkg_nofetch'),
        'AA': ('src_', 'pkg_nofetch'),
        'FILESDIR': 'src_',
        'DISTDIR': 'src_',
        'WORKDIR': 'src_',
        'S': 'src_',
        'PORTDIR': 'src_',
        'ECLASSDIR': 'src_',
        'ROOT': 'pkg_',
        'EROOT': 'pkg_',
        'SYSROOT': ('src_', 'pkg_setup'),
        'ESYSROOT': ('src_', 'pkg_setup'),
        'BROOT': ('src_', 'pkg_setup'),
        'D': ('src_install', 'pkg_preinst', 'pkg_postint'),
        'ED': ('src_install', 'pkg_preinst', 'pkg_postint'),
        'DESTTREE': 'src_install',
        'INSDESTTREE': 'src_install',
        'MERGE_TYPE': 'pkg_',
        'REPLACING_VERSIONS': 'pkg_',
        'REPLACED_BY_VERSION': ('pkg_prerm', 'pkg_postrm'),
    })

    # mapping of bad variables for each EAPI phase function
    scoped_vars = {}
    for eapi in EAPI.known_eapis.values():
        for variable, allowed_scopes in variable_map.items():
            for phase in eapi.phases_rev:
                if not phase.startswith(allowed_scopes):
                    scoped_vars.setdefault(eapi, {}).setdefault(phase, set()).add(variable)
    scoped_vars = ImmutableDict(scoped_vars)

    def feed(self, pkg):
        for func_node, _ in bash.func_query.captures(pkg.tree.root_node):
            func_name = pkg.node_str(func_node.child_by_field_name('name'))
            if variables := self.scoped_vars[pkg.eapi].get(func_name):
                usage = defaultdict(set)
                for var_node, _ in bash.var_query.captures(func_node):
                    var_name = pkg.node_str(var_node)
                    if var_name in variables:
                        lineno, colno = var_node.start_point
                        usage[var_name].add(lineno + 1)
                for var, lines in sorted(usage.items()):
                    yield EbuildVariableScope(var, func_name, lines=sorted(lines), pkg=pkg)


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


class UnquotedVariable(results.BaseLinesResult, results.AliasResult, results.Warning):
    """Variable is used unquoted in a context where it should be quoted.

    Variables like D, FILESDIR, etc may not be safe to use unquoted in some
    contexts.
    """

    _name = 'UnquotedVariable'

    def __init__(self, variable, **kwargs):
        super().__init__(**kwargs)
        self.variable = variable

    @property
    def desc(self):
        return f'unquoted variable {self.variable} {self.lines_str}'


class EbuildUnquotedVariable(UnquotedVariable, results.VersionResult):
    __doc__ = UnquotedVariable.__doc__


class EclassUnquotedVariable(UnquotedVariable, results.EclassResult):
    __doc__ = UnquotedVariable.__doc__

    @property
    def desc(self):
        return f'{self.eclass}: {super().desc}'


class _UnquotedVariablesCheck(Check):
    """Scan files for variables that should be quoted like D, FILESDIR, etc."""

    message_commands = frozenset({
        "die", "echo", "eerror", "einfo", "elog", "eqawarn", "ewarn", ":"
    })
    var_names = frozenset({
        "D", "DISTDIR", "FILESDIR", "S", "T", "ROOT", "BROOT", "WORKDIR", "ED",
        "EPREFIX", "EROOT", "SYSROOT", "ESYSROOT", "TMPDIR", "HOME",
        # variables for multibuild.eclass
        "BUILD_DIR",
    })

    node_types_ok = frozenset({
        # Variable is sitting in a string, all good
        'string',
        # Variable is part of a shell assignment, and does not need to be
        # quoted. for example S=${WORKDIR}/${PN} is ok.
        'variable_assignment',
        # Variable sits inside a [[ ]] test command and it's OK not to be quoted
        'test_command',
        # Variable is being used in a heredoc body, no need to specify quotes.
        'heredoc_body',
    })

    def _var_needs_quotes(self, pkg, node):
        pnode = node.parent
        while pnode != node:
            if pnode.type in self.node_types_ok:
                return False
            elif pnode.type == 'command':
                cmd = pkg.node_str(pnode.child_by_field_name('name'))
                return cmd not in self.message_commands
            elif pnode.type in 'array':
                # Variable is sitting unquoted in an array
                return True
            pnode = pnode.parent

        # Default: The variable should be quoted
        return True

    def _feed(self, item):
        if item.tree.root_node.has_error:
            # Do not run this check if the parse tree contains errors, as it
            # might result in false positives. This check appears to be quite
            # expensive though...
            return
        hits = defaultdict(set)
        for var_node, _ in bash.var_query.captures(item.tree.root_node):
            var_name = item.node_str(var_node)
            if var_name in self.var_names:
                if self._var_needs_quotes(item, var_node):
                    lineno, _ = var_node.start_point
                    hits[var_name].add(lineno+1)
        for var_name, lines in hits.items():
            yield var_name, sorted(lines)


class EbuildUnquotedVariablesCheck(_UnquotedVariablesCheck):
    """Scan ebuild for variables that should be quoted like D, FILESDIR, etc."""

    _source = sources.EbuildParseRepoSource
    known_results = frozenset([EbuildUnquotedVariable])

    def feed(self, pkg):
        for var_name, lines in self._feed(pkg):
            yield EbuildUnquotedVariable(var_name, lines=lines, pkg=pkg)


class EclassUnquotedVariablesCheck(_UnquotedVariablesCheck):
    """Scan eclass for variables that should be quoted like D, FILESDIR, etc."""

    _source = sources.EclassParseRepoSource
    known_results = frozenset([EclassUnquotedVariable])
    required_addons = (addons.eclass.EclassAddon,)

    def feed(self, eclass):
        for var_name, lines in self._feed(eclass):
            yield EclassUnquotedVariable(var_name, lines=lines, eclass=eclass.name)
