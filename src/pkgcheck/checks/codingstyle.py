"""Various line-based checks."""

import re
from collections import defaultdict

from pkgcore.ebuild.eapi import EAPI, common_mandatory_metadata_keys
from snakeoil.mappings import ImmutableDict
from snakeoil.sequences import stable_unique
from snakeoil.strings import pluralism

from .. import addons, bash
from .. import results, sources
from . import Check

PREFIX_VARIABLES = ("EROOT", "ED", "EPREFIX")
PATH_VARIABLES = ("BROOT", "ROOT", "D") + PREFIX_VARIABLES


class _CommandResult(results.LineResult):
    """Generic command result."""

    def __init__(self, command, **kwargs):
        super().__init__(**kwargs)
        self.command = command

    @property
    def usage_desc(self):
        return f"{self.command!r}"

    @property
    def desc(self):
        s = f"{self.usage_desc}, used on line {self.lineno}"
        if self.line != self.command:
            s += f": {self.line!r}"
        return s


class _EapiCommandResult(_CommandResult):
    """Generic EAPI command result."""

    _status = None

    def __init__(self, *args, eapi, **kwargs):
        super().__init__(*args, **kwargs)
        self.eapi = str(eapi)

    @property
    def usage_desc(self):
        return f"{self.command!r} {self._status} in EAPI {self.eapi}"


class DeprecatedEapiCommand(_EapiCommandResult, results.Warning):
    """Ebuild uses a deprecated EAPI command."""

    _status = "deprecated"


class BannedEapiCommand(_EapiCommandResult, results.Error):
    """Ebuild uses a banned EAPI command."""

    _status = "banned"


class BannedPhaseCall(results.Error, results.LineResult):
    """Ebuild calls a phase function directly."""

    @property
    def desc(self):
        return f"line {self.lineno}: calling phase function {self.line!r} directly is invalid"


class BadCommandsCheck(Check):
    """Scan ebuild for various deprecated and banned command usage."""

    _source = sources.EbuildParseRepoSource
    known_results = frozenset({DeprecatedEapiCommand, BannedEapiCommand, BannedPhaseCall})

    extra_banned_commands = frozenset(
        {
            # commands that modify user/group databases, not portable
            "gpasswd",
            "groupadd",
            "groupdel",
            "groupmod",
            "useradd",
            "userdel",
            "usermod",
        }
    )

    def feed(self, pkg):
        for func_node in bash.func_query.captures(pkg.tree.root_node).get("func", ()):
            for node in bash.cmd_query.captures(func_node).get("call", ()):
                call = pkg.node_str(node)
                name = pkg.node_str(node.child_by_field_name("name"))
                lineno, _colno = node.start_point
                if name in pkg.eapi.bash_cmds_banned:
                    yield BannedEapiCommand(
                        name, line=call, lineno=lineno + 1, eapi=pkg.eapi, pkg=pkg
                    )
                elif name in pkg.eapi.bash_cmds_deprecated:
                    yield DeprecatedEapiCommand(
                        name, line=call, lineno=lineno + 1, eapi=pkg.eapi, pkg=pkg
                    )
                elif name in pkg.eapi.phases.values():
                    yield BannedPhaseCall(line=name, lineno=lineno + 1, pkg=pkg)
                elif name in ("has_version", "best_version"):
                    if not pkg.eapi.options.query_host_root and any(
                        pkg.node_str(n) == "--host-root"
                        for n in node.children_by_field_name("argument")
                    ):
                        name = f"{name} --host-root"
                        yield BannedEapiCommand(
                            name, line=call, lineno=lineno + 1, eapi=pkg.eapi, pkg=pkg
                        )
                elif name in self.extra_banned_commands:
                    yield BannedEapiCommand(
                        name, line=call, lineno=lineno + 1, eapi=pkg.eapi, pkg=pkg
                    )


class EendMissingArg(results.LineResult, results.Warning):
    """Ebuild calls eend with no arguments."""

    @property
    def desc(self):
        return f"eend with no arguments, on line {self.lineno}"


class EendMissingArgCheck(Check):
    """Scan an ebuild for calls to eend with no arguments."""

    _source = sources.EbuildParseRepoSource
    known_results = frozenset([EendMissingArg])

    def feed(self, pkg):
        for func_node in bash.func_query.captures(pkg.tree.root_node).get("func", ()):
            for node in bash.cmd_query.captures(func_node).get("call", ()):
                line = pkg.node_str(node)
                if line == "eend":
                    lineno, _ = node.start_point
                    yield EendMissingArg(line=line, lineno=lineno + 1, pkg=pkg)


class MissingSlash(results.LinesResult, results.Error):
    """Ebuild uses a path variable missing a trailing slash."""

    def __init__(self, match, **kwargs):
        super().__init__(**kwargs)
        self.match = match

    @property
    def desc(self):
        return f"{self.match} missing trailing slash {self.lines_str}"


class UnnecessarySlashStrip(results.LinesResult, results.Style):
    """Ebuild uses a path variable that strips a nonexistent slash."""

    def __init__(self, match, **kwargs):
        super().__init__(**kwargs)
        self.match = match

    @property
    def desc(self):
        return f"{self.match} unnecessary slash strip {self.lines_str}"


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
        return f"{self.match}: concatenates two paths containing EPREFIX {self.lines_str}"


class PathVariablesCheck(Check):
    """Scan ebuild for path variables with various issues."""

    _source = sources.EbuildFileRepoSource
    known_results = frozenset({MissingSlash, UnnecessarySlashStrip, DoublePrefixInPath})
    prefixed_dir_functions = (
        "insinto",
        "exeinto",
        "dodir",
        "keepdir",
        "fowners",
        "fperms",
        # java-pkg-2
        "java-pkg_jarinto",
        "java-pkg_sointo",
        # python-utils-r1
        "python_scriptinto",
        "python_moduleinto",
    )
    # TODO: add variables to mark this status in the eclasses in order to pull
    # this data from parsed eclass docs
    prefixed_getters = (
        # bash-completion-r1.eclass
        "get_bashcompdir",
        "get_bashhelpersdir",
        # db-use.eclass
        "db_includedir",
        # golang-base.eclass
        "get_golibdir_gopath",
        # llvm.eclass
        "get_llvm_prefix",
        # python-utils-r1.eclass
        "python_get_sitedir",
        "python_get_includedir",
        "python_get_library_path",
        "python_get_scriptdir",
        # qmake-utils.eclass
        "qt4_get_bindir",
        "qt5_get_bindir",
        "qt6_get_bindir",
        # s6.eclass
        "s6_get_servicedir",
        # shell-completion.eclass
        "get_fishcompdir",
        "get_zshcompdir",
        # systemd.eclass
        "systemd_get_systemunitdir",
        "systemd_get_userunitdir",
        "systemd_get_utildir",
        "systemd_get_systemgeneratordir",
        "systemd_get_systempresetdir",
        "systemd_get_sleepdir",
    )
    prefixed_rhs_variables = (
        # catch silly ${ED}${EPREFIX} mistake ;-)
        "EPREFIX",
        # python-utils-r1.eclass
        "PYTHON",
        "PYTHON_SITEDIR",
        "PYTHON_INCLUDEDIR",
        "PYTHON_LIBPATH",
        "PYTHON_CONFIG",
        "PYTHON_SCRIPTDIR",
    )

    def __init__(self, *args):
        super().__init__(*args)
        self.missing_regex = re.compile(r'(\${(%s)})"?\w+/' % r"|".join(PATH_VARIABLES))
        self.unnecessary_regex = re.compile(r"(\${(%s)%%/})" % r"|".join(PATH_VARIABLES))
        self.double_prefix_regex = re.compile(
            r"(\${(%s)(%%/)?}/?\$(\((%s)\)|{(%s)}))"
            % (
                r"|".join(PREFIX_VARIABLES),
                r"|".join(self.prefixed_getters),
                r"|".join(self.prefixed_rhs_variables),
            )
        )
        self.double_prefix_func_regex = re.compile(
            r"\b(%s)\s[^&|;]*\$(\((%s)\)|{(%s)})"
            % (
                r"|".join(self.prefixed_dir_functions),
                r"|".join(self.prefixed_getters),
                r"|".join(self.prefixed_rhs_variables),
            )
        )
        # do not catch ${foo#${EPREFIX}} and similar
        self.double_prefix_func_false_positive_regex = re.compile(
            r'.*?[#]["]?\$(\((%s)\)|{(%s)})'
            % (r"|".join(self.prefixed_getters), r"|".join(self.prefixed_rhs_variables))
        )

    def feed(self, pkg):
        missing = defaultdict(list)
        unnecessary = defaultdict(list)
        double_prefix = defaultdict(list)

        for lineno, line in enumerate(pkg.lines, 1):
            line = line.strip()
            if not line:
                continue

            # flag double path prefix usage on uncommented lines only
            if line[0] != "#":
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

    DIRS = ("bin", "etc", "lib", "opt", "sbin", "srv", "usr", "var")

    def __init__(self, *args):
        super().__init__(*args)
        dirs = "|".join(self.DIRS)
        path_vars = "|".join(PATH_VARIABLES)
        prefixed_regex = rf'"\${{({path_vars})(%/)?}}(?P<cp>")?(?(cp)\S*|.*?")'
        non_prefixed_regex = rf'(?P<op>["\'])?/({dirs})(?(op).*?(?P=op)|\S*)'
        self.regex = re.compile(rf"^\s*(?P<cmd>dosym\s+({prefixed_regex}|{non_prefixed_regex}))")

    def feed(self, pkg):
        for lineno, line in enumerate(pkg.lines, 1):
            if not line.strip():
                continue
            if mo := self.regex.match(line):
                yield AbsoluteSymlink(mo.group("cmd"), line=line, lineno=lineno, pkg=pkg)


class DeprecatedInsinto(results.LineResult, results.Warning):
    """Ebuild uses insinto where more compact commands exist."""

    def __init__(self, cmd, **kwargs):
        super().__init__(**kwargs)
        self.cmd = cmd

    @property
    def desc(self):
        return (
            f"deprecated insinto usage (use {self.cmd} instead), "
            f"line {self.lineno}: {self.line}"
        )


class InsintoCheck(Check):
    """Scan ebuild for deprecated insinto usage."""

    _source = sources.EbuildFileRepoSource
    known_results = frozenset([DeprecatedInsinto])

    path_mapping = ImmutableDict(
        {
            "/etc/conf.d": "doconfd or newconfd",
            "/etc/env.d": "doenvd or newenvd",
            "/etc/init.d": "doinitd or newinitd",
            "/etc/pam.d": "dopamd or newpamd from pam.eclass",
            "/usr/lib/systemd/system": "systemd_dounit or systemd_newunit from systemd.eclass",
            "/usr/lib/systemd/user": "systemd_douserunit or systemd_newuserunit from systemd.eclass",
            "/usr/share/applications": "domenu or newmenu from desktop.eclass",
            "/usr/share/fish/vendor_completions.d": "dofishcomp or newfishcomp from shell-completion.eclass",
            "/usr/share/zsh/site-functions": "dozshcomp or newzshcomp from shell-completion.eclass",
        }
    )

    def __init__(self, *args):
        super().__init__(*args)
        paths = "|".join(s.replace("/", "/+") + "/?" for s in self.path_mapping)
        self._insinto_re = re.compile(
            rf"(?P<insinto>insinto[ \t]+(?P<path>{paths})(?!/\w+))(?:$|[/ \t])"
        )
        self._insinto_doc_re = re.compile(
            r'(?P<insinto>insinto[ \t]+/usr/share/doc/(")?\$\{PF?\}(?(2)\2)(/\w+)*)(?:$|[/ \t])'
        )

    def feed(self, pkg):
        for lineno, line in enumerate(pkg.lines, 1):
            if not line.strip():
                continue
            matches = self._insinto_re.search(line)
            if matches is not None:
                path = re.sub("//+", "/", matches.group("path"))
                cmd = self.path_mapping[path.rstrip("/")]
                yield DeprecatedInsinto(cmd, line=matches.group("insinto"), lineno=lineno, pkg=pkg)
                continue
            # Check for insinto usage that should be replaced with
            # docinto/dodoc [-r] under supported EAPIs.
            if pkg.eapi.options.dodoc_allow_recursive:
                matches = self._insinto_doc_re.search(line)
                if matches is not None:
                    yield DeprecatedInsinto(
                        "docinto/dodoc", line=matches.group("insinto"), lineno=lineno, pkg=pkg
                    )


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
        return (
            f"obsolete fetch URI: {self.uri} on line "
            f"{self.line}, should be replaced by: {self.replacement}"
        )


class ObsoleteUriCheck(Check):
    """Scan ebuild for obsolete URIs."""

    _source = sources.EbuildFileRepoSource
    known_results = frozenset([ObsoleteUri])

    REGEXPS = (
        (
            r".*\b(?P<uri>(?P<prefix>https?://github\.com/.*?/.*?/)"
            r"(?:tar|zip)ball(?P<ref>\S*))",
            r"\g<prefix>archive\g<ref>.tar.gz",
        ),
        (
            r".*\b(?P<uri>(?P<prefix>https?://gitlab\.com/.*?/(?P<pkg>.*?)/)"
            r"repository/archive\.(?P<format>tar|tar\.gz|tar\.bz2|zip)"
            r"\?ref=(?P<ref>\S*))",
            r"\g<prefix>-/archive/\g<ref>/\g<pkg>-\g<ref>.\g<format>",
        ),
    )

    def __init__(self, *args):
        super().__init__(*args)
        self.regexes = tuple((re.compile(regexp), repl) for regexp, repl in self.REGEXPS)

    def feed(self, pkg):
        for lineno, line in enumerate(pkg.lines, 1):
            if not line.strip() or line.startswith("#"):
                continue
            # searching for multiple matches on a single line is too slow
            for regexp, repl in self.regexes:
                if mo := regexp.match(line):
                    uri = mo.group("uri")
                    yield ObsoleteUri(lineno, uri, regexp.sub(repl, uri), pkg=pkg)


class BetterCompressionUri(results.LineResult, results.Style):
    """URI provider has better compression suggestion.

    The URI used to fetch distfile doesn't use the best compression
    available from the provider. Using better compression can save
    bandwidth for the users and mirrors.
    """

    def __init__(self, replacement, **kwargs):
        super().__init__(**kwargs)
        self.replacement = replacement

    @property
    def desc(self):
        return (
            f"line {self.lineno}: better compression URI using extension "
            f"{self.replacement!r} for {self.line!r}"
        )


class BetterCompressionCheck(Check):
    """Scan ebuild for URIs with better compression."""

    _source = sources.EbuildFileRepoSource
    known_results = frozenset([BetterCompressionUri])

    REGEXPS = (
        (
            r".*\b(?P<uri>https?://[^/]*?gitlab[^/]*?/.*/-/archive/.*?/\S*\.(?:tar\.gz|tar(?!.bz2)|zip))",
            ".tar.bz2",
        ),
    )

    def __init__(self, *args):
        super().__init__(*args)
        self.regexes = tuple((re.compile(regexp), repl) for regexp, repl in self.REGEXPS)

    def feed(self, pkg):
        for lineno, line in enumerate(pkg.lines, 1):
            if not line.strip() or line.startswith("#"):
                continue
            # searching for multiple matches on a single line is too slow
            for regexp, replacement in self.regexes:
                if mo := regexp.match(line):
                    uri = mo.group("uri")
                    yield BetterCompressionUri(replacement, lineno=lineno, line=uri, pkg=pkg)


class HomepageInSrcUri(results.VersionResult, results.Style):
    """${HOMEPAGE} is referenced in SRC_URI.

    SRC_URI is built on top of ${HOMEPAGE}. This is discouraged since HOMEPAGE
    is multi-valued by design, and is subject to potential changes that should
    not accidentally affect SRC_URI.
    """

    @property
    def desc(self):
        return "${HOMEPAGE} in SRC_URI"


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
        return f"{self.static_str!r} in SRC_URI, replace with {self.replacement}"


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
        refs = ", ".join(self.refs)
        return f"{self.variable} includes variable{s}: {refs}"


class MultipleKeywordsLines(results.LinesResult, results.Style):
    """KEYWORDS is specified across multiple lines in global scope.

    Due to limitations of ekeyword it's advised to specify KEYWORDS once on a
    single line in global scope [#]_.

    .. [#] https://projects.gentoo.org/qa/policy-guide/ebuild-format.html#pg0105
    """

    @property
    def desc(self):
        return f"KEYWORDS specified {self.lines_str}"


class EmptyGlobalAssignment(results.LineResult, results.Style):
    """Global scope useless empty assignment."""

    @property
    def desc(self):
        return f"line {self.lineno}: empty global assignment: {self.line}"


class SelfAssignment(results.LineResult, results.Warning):
    """Global scope useless empty assignment."""

    @property
    def desc(self):
        return f"line {self.lineno}: self assignment: {self.line}"


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
    known_results = frozenset(
        {
            HomepageInSrcUri,
            StaticSrcUri,
            ReferenceInMetadataVar,
            MultipleKeywordsLines,
            EmptyGlobalAssignment,
            SelfAssignment,
        }
    )

    # mapping between registered variables and verification methods
    known_variables = {}

    empty_vars_whitelist = frozenset({"KEYWORDS"})

    @verify_vars("HOMEPAGE", "KEYWORDS")
    def _raw_text(self, var, node, value, pkg):
        matches = []
        for var_node in bash.var_query.captures(node).get("var", ()):
            matches.append(pkg.node_str(var_node.parent))
        if matches:
            yield ReferenceInMetadataVar(var, stable_unique(matches), pkg=pkg)

    @verify_vars("LICENSE")
    def _raw_text_license(self, var, node, value, pkg):
        matches = []
        for var_node in bash.var_query.captures(node).get("var", ()):
            var_str = pkg.node_str(var_node.parent).strip()
            if var_str in ["$LICENSE", "${LICENSE}"]:
                continue  # LICENSE in LICENSE is ok
            matches.append(var_str)
        if matches:
            yield ReferenceInMetadataVar(var, stable_unique(matches), pkg=pkg)

    def build_src_uri_variants_regex(self, pkg):
        p, pv = pkg.P, pkg.PV
        replacements = {p: "${P}", pv: "${PV}"}
        replacements.setdefault(p.capitalize(), "${P^}")
        replacements.setdefault(p.upper(), "${P^^}")

        for value, replacement in tuple(replacements.items()):
            replacements.setdefault(value.replace(".", ""), replacement.replace("}", "//.}"))
            replacements.setdefault(value.replace(".", "_"), replacement.replace("}", "//./_}"))
            replacements.setdefault(value.replace(".", "-"), replacement.replace("}", "//./-}"))

        pos = 0
        positions = [pos := pv.find(".", pos + 1) for _ in range(pv.count("."))]

        for sep in ("", "-", "_"):
            replacements.setdefault(pv.replace(".", sep, 1), f"$(ver_rs 1 {sep!r})")
            for count in range(2, pv.count(".")):
                replacements.setdefault(pv.replace(".", sep, count), f"$(ver_rs 1-{count} {sep!r})")

        for pos, index in enumerate(positions[1:], start=2):
            replacements.setdefault(pv[:index], f"$(ver_cut 1-{pos})")

        replacements = sorted(replacements.items(), key=lambda x: -len(x[0]))

        return tuple(zip(*replacements))[1], "|".join(
            rf"(?P<r{index}>{re.escape(s)})" for index, (s, _) in enumerate(replacements)
        )

    @verify_vars("SRC_URI")
    def _src_uri(self, var, node, value, pkg):
        if "${HOMEPAGE}" in value:
            yield HomepageInSrcUri(pkg=pkg)

        replacements, regex = self.build_src_uri_variants_regex(pkg)
        static_src_uri_re = rf"(?:/|{re.escape(pkg.PN)}[-._]?|->\s*)[v]?(?P<static_str>({regex}))"
        static_urls = {}
        for match in re.finditer(static_src_uri_re, value):
            relevant = {key: value for key, value in match.groupdict().items() if value is not None}
            static_str = relevant.pop("static_str")
            assert len(relevant) == 1
            key = int(tuple(relevant.keys())[0][1:])
            static_urls[static_str] = replacements[key]

        for static_str, replacement in static_urls.items():
            yield StaticSrcUri(static_str, replacement=replacement, pkg=pkg)

    def canonicalize_assign(self, value: str):
        return value.strip("\"'").replace("\n", "").replace("\t", " ")

    def feed(self, pkg):
        keywords_lines = set()
        for node in pkg.global_query(bash.var_assign_query):
            name = pkg.node_str(node.child_by_field_name("name"))
            value_node = node.child_by_field_name("value")
            value_str = self.canonicalize_assign(pkg.node_str(value_node)) if value_node else ""
            if name in pkg.eapi.eclass_keys:
                if not value_str:
                    if name not in self.empty_vars_whitelist:
                        lineno, _ = node.start_point
                        yield EmptyGlobalAssignment(
                            line=pkg.node_str(node), lineno=lineno + 1, pkg=pkg
                        )
                elif pkg.node_str(value_node.prev_sibling) == "=":
                    for var_node in bash.var_query.captures(value_node).get("var", ()):
                        if (
                            pkg.node_str(var_node) == name
                            and self.canonicalize_assign(pkg.node_str(var_node.parent)) == value_str
                            and var_node.next_named_sibling is None
                        ):
                            node_str = pkg.node_str(node).replace("\n", "").replace("\t", " ")
                            lineno, _ = node.start_point
                            yield SelfAssignment(line=node_str, lineno=lineno + 1, pkg=pkg)
            if name in self.known_variables:
                if name == "KEYWORDS":
                    keywords_lines.add(node.start_point[0] + 1)
                    keywords_lines.add(node.end_point[0] + 1)
                yield from self.known_variables[name](self, name, value_node, value_str, pkg)

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
        return f"{self.eclass}: missing inherit usage: {repr(self.usage)}, line {self.lineno}"


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
        return f"{self.eclass}: indirect inherit usage: {repr(self.usage)}, line {self.lineno}"


class UnusedInherits(results.VersionResult, results.Warning):
    """Ebuild inherits eclasses that are unused."""

    def __init__(self, eclasses, **kwargs):
        super().__init__(**kwargs)
        self.eclasses = tuple(eclasses)

    @property
    def desc(self):
        es = pluralism(self.eclasses, plural="es")
        eclasses = ", ".join(self.eclasses)
        return f"unused eclass{es}: {eclasses}"


class InternalEclassUsage(results.VersionResult, results.Warning):
    """Ebuild uses internal functions or variables from eclass."""

    def __init__(self, eclass, lineno, usage, **kwargs):
        super().__init__(**kwargs)
        self.eclass = eclass
        self.lineno = lineno
        self.usage = usage

    @property
    def desc(self):
        return f"{self.eclass}: internal usage: {repr(self.usage)}, line {self.lineno}"


class InheritsCheck(Check):
    """Scan for ebuilds with missing or unused eclass inherits.

    Note that this requires using ``pmaint regen`` to generate repo metadata in
    order for direct inherits to be correct.
    """

    _source = sources.EbuildParseRepoSource
    known_results = frozenset(
        [MissingInherits, IndirectInherits, UnusedInherits, InternalEclassUsage]
    )
    required_addons = (addons.eclass.EclassAddon,)

    def __init__(self, *args, eclass_addon):
        super().__init__(*args)
        self.eclass_cache = eclass_addon.eclasses
        self.internals = {}
        self.exported = {}

        # register internal and exported funcs/vars for all eclasses
        for eclass, eclass_obj in self.eclass_cache.items():
            self.internals[eclass] = (
                eclass_obj.internal_function_names | eclass_obj.internal_variable_names
            )
            for name in eclass_obj.exported_function_names:
                self.exported.setdefault(name, set()).add(eclass)
            # Don't use all exported vars in order to avoid
            # erroneously exported temporary loop variables that
            # should be flagged via EclassDocMissingVar.
            for name in eclass_obj.variable_names:
                self.exported.setdefault(name, set()).add(eclass)

        # collect all @USER_VARIABLEs, which are excluded from MissingInherits
        user_variables = frozenset(
            {
                x.name
                for eclass_obj in self.eclass_cache.values()
                for x in eclass_obj.variables
                if x.user_variable
            }
        )
        self.exclude_missing_inherit = user_variables | {"CTARGET", "BUILD_DIR"}

        # register EAPI-related funcs/cmds to ignore
        self.eapi_funcs = {}
        for eapi in EAPI.known_eapis.values():
            s = set(eapi.bash_cmds_internal | eapi.bash_cmds_deprecated)
            s.update(x for x in (eapi.bash_funcs | eapi.bash_funcs_global) if not x.startswith("_"))
            self.eapi_funcs[eapi] = frozenset(s)

        # register EAPI-related vars to ignore
        # TODO: add ebuild env vars via pkgcore setting, e.g. PN, PV, P, FILESDIR, etc
        self.eapi_vars = {eapi: frozenset(eapi.eclass_keys) for eapi in EAPI.known_eapis.values()}

        self.unused_eclass_skiplist = frozenset(common_mandatory_metadata_keys) - {"IUSE"}

        self.weak_eclass_usage = {"elisp": ("readme.gentoo-r1",)}

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

        # collect globally defined functions in ebuild
        defined_funcs = {
            pkg.node_str(func_node.child_by_field_name("name"))
            for func_node in bash.func_query.captures(pkg.tree.root_node).get("func", ())
        }

        # register variables assigned in ebuilds
        assigned_vars = dict()
        for node in bash.var_assign_query.captures(pkg.tree.root_node).get("assign", ()):
            name = pkg.node_str(node.child_by_field_name("name"))
            if eclass := self.get_eclass(name, pkg):
                assigned_vars[name] = eclass

        # eclasses which might be used indirectly, so we won't trigger UnusedInherits
        weak_used_eclasses = set()
        # match captured commands with eclasses
        used = defaultdict(list)
        for node in bash.cmd_query.captures(pkg.tree.root_node).get("call", ()):
            call = pkg.node_str(node)
            name = pkg.node_str(node.child_by_field_name("name"))
            if name == "inherit":
                # register conditional eclasses
                eclasses = call.split()[1:]
                if not pkg.inherited.intersection(eclasses):
                    conditional.update(eclasses)
                continue
            # Also ignore vars since any used in arithmetic expansions, i.e.
            # $((...)), are captured as commands.
            elif name not in self.eapi_funcs[pkg.eapi] | assigned_vars.keys() | defined_funcs:
                lineno, _colno = node.start_point
                if eclass := self.get_eclass(name, pkg):
                    used[eclass].append((lineno + 1, name, call.split("\n", 1)[0]))

            for arg in node.children[1:]:
                arg_name = pkg.node_str(arg).strip("'\"")
                if eclass := self.get_eclass(arg_name, pkg):
                    weak_used_eclasses.add(eclass)

        # match captured variables with eclasses
        for node in bash.var_query.captures(pkg.tree.root_node).get("var", ()):
            name = pkg.node_str(node)
            if node.parent.type == "unset_command":
                continue
            if name not in self.eapi_vars[pkg.eapi] | assigned_vars.keys():
                if name in self.exclude_missing_inherit:
                    continue
                lineno, _colno = node.start_point
                if eclass := self.get_eclass(name, pkg):
                    used[eclass].append((lineno + 1, name, name))

        # allowed indirect inherits
        indirect_allowed = set().union(*(self.eclass_cache[x].provides for x in pkg.inherit))
        all_inherits = set().union(pkg.inherit, indirect_allowed, conditional)
        # missing inherits
        missing = used.keys() - all_inherits

        for eclass in all_inherits:
            weak_used_eclasses.update(self.weak_eclass_usage.get(eclass, ()))

        unused = set(pkg.inherit) - used.keys() - set(assigned_vars.values()) - weak_used_eclasses
        # remove eclasses that use implicit phase functions
        if unused and pkg.defined_phases:
            phases = [pkg.eapi.phases[x] for x in pkg.defined_phases]
            for eclass in list(unused):
                if self.eclass_cache[eclass].exported_function_names.intersection(
                    f"{eclass}_{phase}" for phase in phases
                ):
                    unused.discard(eclass)

        for eclass in list(unused):
            if self.eclass_cache[eclass].name is None:
                # ignore eclasses with parsing failures
                unused.discard(eclass)
            else:
                exported_eclass_keys: set[str] = pkg.eapi.eclass_keys.intersection(
                    self.eclass_cache[eclass].exported_variable_names
                )
                if exported_eclass_keys.intersection(self.unused_eclass_skiplist):
                    unused.discard(eclass)
                elif not self.eclass_cache[eclass].exported_function_names and exported_eclass_keys:
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
    readonly_vars = frozenset(
        [
            "P",
            "PN",
            "PV",
            "PR",
            "PVR",
            "PF",
            "A",
            "CATEGORY",
            "FILESDIR",
            "WORKDIR",
            "T",
            "D",
            "HOME",
            "ROOT",
            "DISTDIR",
            "EPREFIX",
            "ED",
            "EROOT",
            "SYSROOT",
            "ESYSROOT",
            "BROOT",
            "MERGE_TYPE",
            "REPLACING_VERSIONS",
            "REPLACED_BY_VERSION",
        ]
    )

    def feed(self, pkg):
        for node in pkg.global_query(bash.var_assign_query):
            name = pkg.node_str(node.child_by_field_name("name"))
            if name in self.readonly_vars:
                call = pkg.node_str(node)
                lineno, _colno = node.start_point
                yield ReadonlyVariable(name, line=call, lineno=lineno + 1, pkg=pkg)


class VariableScope(results.BaseLinesResult, results.AliasResult, results.Warning):
    """Variable used outside its defined scope."""

    _name = "VariableScope"

    def __init__(self, variable, func, **kwargs):
        super().__init__(**kwargs)
        self.variable = variable
        self.func = func

    @property
    def desc(self):
        return f"variable {self.variable!r} used in {self.func!r} {self.lines_str}"


class EbuildVariableScope(VariableScope, results.VersionResult):
    """Ebuild using variable outside its defined scope."""


class VariableScopeCheck(Check):
    """Scan ebuilds for variables that are only allowed in certain scopes."""

    _source = sources.EbuildParseRepoSource
    known_results = frozenset({EbuildVariableScope})

    # see https://projects.gentoo.org/pms/7/pms.html#x1-10900011.1
    variable_map = ImmutableDict(
        {
            "A": ("src_", "pkg_nofetch"),
            "AA": ("src_", "pkg_nofetch"),
            "FILESDIR": "src_",
            "DISTDIR": "src_",
            "WORKDIR": "src_",
            "S": "src_",
            "PORTDIR": "src_",
            "ECLASSDIR": "src_",
            "ROOT": "pkg_",
            "EROOT": "pkg_",
            "SYSROOT": ("src_", "pkg_setup"),
            "ESYSROOT": ("src_", "pkg_setup"),
            "BROOT": ("src_", "pkg_setup", "pkg_preinst", "pkg_prerm", "pkg_post"),
            "D": ("src_install", "pkg_preinst"),  # pkg_postinst is forbidden by QA policy PG 107
            "ED": ("src_install", "pkg_preinst"),  # pkg_postinst is forbidden by QA policy PG 107
            "DESTTREE": "src_install",
            "INSDESTTREE": "src_install",
            "MERGE_TYPE": "pkg_",
            "REPLACING_VERSIONS": "pkg_",
            "REPLACED_BY_VERSION": ("pkg_prerm", "pkg_postrm"),
        }
    )

    not_global_scope = frozenset(
        {
            "A",
            "AA",
            "BROOT",
            "D",
            "DESTTREE",
            "ECLASSDIR",
            "ED",
            "EROOT",
            "ESYSROOT",
            "INSDESTTREE",
            "MERGE_TYPE",
            "PORTDIR",
            "REPLACED_BY_VERSION",
            "REPLACING_VERSIONS",
            "ROOT",
            "SYSROOT",
        }
    )

    # mapping of bad variables for each EAPI phase function
    scoped_vars = {}
    for eapi in EAPI.known_eapis.values():
        for variable, allowed_scopes in variable_map.items():
            for phase in eapi.phases_rev:
                if not phase.startswith(allowed_scopes):
                    scoped_vars.setdefault(eapi, {}).setdefault(phase, set()).add(variable)
    scoped_vars = ImmutableDict(scoped_vars)

    def feed(self, pkg: bash.ParseTree):
        for func_node in bash.func_query.captures(pkg.tree.root_node).get("func", ()):
            func_name = pkg.node_str(func_node.child_by_field_name("name"))
            if variables := self.scoped_vars[pkg.eapi].get(func_name):
                usage = defaultdict(set)
                for var_node in bash.var_query.captures(func_node).get("var", ()):
                    var_name = pkg.node_str(var_node)
                    if var_name in variables:
                        lineno, _colno = var_node.start_point
                        usage[var_name].add(lineno + 1)
                for var, lines in sorted(usage.items()):
                    yield EbuildVariableScope(var, func_name, lines=sorted(lines), pkg=pkg)

        global_usage = defaultdict(set)
        for global_node in pkg.tree.root_node.children:
            if global_node.type not in ("function_definition", "ERROR"):
                for var_node in bash.var_query.captures(global_node).get("var", ()):
                    var_name = pkg.node_str(var_node)
                    if var_name in self.not_global_scope:
                        lineno, _colno = var_node.start_point
                        global_usage[var_name].add(lineno + 1)
        for var, lines in sorted(global_usage.items()):
            yield EbuildVariableScope(var, "global scope", lines=sorted(lines), pkg=pkg)


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
        cmds = r"|".join(("insinto", "exeinto", "docinto"))
        self.cmds_regex = re.compile(rf"^\s*(?P<cmd>({cmds}))\s+(?P<path>\S+)")
        self.dodir_regex = re.compile(r"^\s*(?P<call>dodir\s+(?P<path>\S+))")

    def feed(self, pkg):
        lines = enumerate(pkg.lines, 1)
        for lineno, line in lines:
            line = line.strip()
            if not line or line[0] == "#":
                continue
            if dodir := self.dodir_regex.match(line):
                lineno, line = next(lines)
                if cmd := self.cmds_regex.match(line):
                    if dodir.group("path") == cmd.group("path"):
                        yield RedundantDodir(
                            cmd.group("cmd"), line=dodir.group("call"), lineno=lineno - 1, pkg=pkg
                        )


class UnquotedVariable(results.BaseLinesResult, results.AliasResult, results.Warning):
    """Variable is used unquoted in a context where it should be quoted.

    Variables like D, FILESDIR, etc may not be safe to use unquoted in some
    contexts.
    """

    _name = "UnquotedVariable"

    def __init__(self, variable, **kwargs):
        super().__init__(**kwargs)
        self.variable = variable

    @property
    def desc(self):
        return f"unquoted variable {self.variable} {self.lines_str}"


class EbuildUnquotedVariable(UnquotedVariable, results.VersionResult):
    __doc__ = UnquotedVariable.__doc__


class EclassUnquotedVariable(UnquotedVariable, results.EclassResult):
    __doc__ = UnquotedVariable.__doc__

    @property
    def desc(self):
        return f"{self.eclass}: {super().desc}"


class _UnquotedVariablesCheck(Check):
    """Scan files for variables that should be quoted like D, FILESDIR, etc."""

    message_commands = frozenset(
        {"die", "echo", "eerror", "einfo", "elog", "eqawarn", "ewarn", ":"}
    )
    var_names = frozenset(
        {
            "D",
            "DISTDIR",
            "FILESDIR",
            "S",
            "T",
            "ROOT",
            "BROOT",
            "WORKDIR",
            "ED",
            "EPREFIX",
            "EROOT",
            "SYSROOT",
            "ESYSROOT",
            "TMPDIR",
            "HOME",
            # variables for multibuild.eclass
            "BUILD_DIR",
        }
    )

    node_types_ok = frozenset(
        {
            # Variable is sitting in a string, all good
            "string",
            # Variable is part of a shell assignment, and does not need to be
            # quoted. for example S=${WORKDIR}/${PN} is ok.
            "variable_assignment",
            # Variable is being used in a unset command.
            "unset_command",
            # Variable is part of declaring variables, and does not need to be
            # quoted. for example local TMPDIR is ok.
            "declaration_command",
            # Variable sits inside a [[ ]] test command and it's OK not to be quoted
            "test_command",
            # Variable is being used in a heredoc body, no need to specify quotes.
            "heredoc_body",
        }
    )

    def _var_needs_quotes(self, pkg, node):
        pnode = node.parent
        while pnode is not None:
            if pnode.type in self.node_types_ok:
                return False
            elif pnode.type == "command":
                cmd = pkg.node_str(pnode.child_by_field_name("name"))
                return cmd not in self.message_commands
            elif pnode.type in "array":
                # Variable is sitting unquoted in an array
                return True
            pnode = pnode.parent

        # Default: The variable should be quoted
        return True

    def _feed(self, item: bash.ParseTree):
        if item.tree.root_node.has_error:
            # Do not run this check if the parse tree contains errors, as it
            # might result in false positives. This check appears to be quite
            # expensive though...
            return
        hits = defaultdict(set)
        for var_node in bash.var_query.captures(item.tree.root_node).get("var", ()):
            var_name = item.node_str(var_node)
            if var_name in self.var_names:
                if self._var_needs_quotes(item, var_node):
                    lineno, _ = var_node.start_point
                    hits[var_name].add(lineno + 1)
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


class ExcessiveLineLength(results.LinesResult, results.Style):
    """Line is longer than 120 characters."""

    line_length = 120
    word_length = 110

    @property
    def desc(self):
        return f"excessive line length (over {self.line_length} characters) {self.lines_str}"


class LineLengthCheck(Check):
    """Scan ebuild for lines with excessive length."""

    _source = sources.EbuildFileRepoSource
    known_results = frozenset([ExcessiveLineLength])

    def __init__(self, options, **kwargs):
        super().__init__(options, **kwargs)
        self.exception = re.compile(r"\s*(?:DESCRIPTION|KEYWORDS|IUSE)=")
        str_length = f"[^'\"]{{{ExcessiveLineLength.word_length},}}"
        self.long_string = re.compile(rf'"{str_length}"|\'{str_length}\'')

    def feed(self, pkg):
        lines = []
        for lineno, line in enumerate(pkg.lines, 1):
            if len(line) <= ExcessiveLineLength.line_length:
                continue
            if self.exception.match(line):
                continue  # exception variables which are fine to be long
            if max(map(len, line.split())) > ExcessiveLineLength.word_length:
                continue  # if one part of the line is very long word
            if self.long_string.search(line):
                continue  # skip lines with long quoted string
            lines.append(lineno)
        if lines:
            yield ExcessiveLineLength(lines=lines, pkg=pkg)


class InstallCompressedManpage(results.LineResult, results.Warning):
    """Compressed manpages are not supported by ``doman`` or ``newman``."""

    def __init__(self, func, **kwargs):
        super().__init__(**kwargs)
        self.func = func

    @property
    def desc(self):
        return f"line {self.lineno}: compressed manpage {self.line!r} passed to {self.func}"


class InstallCompressedInfo(results.LineResult, results.Warning):
    """Compressed manpages are not supported by ``doinfo``."""

    def __init__(self, func, **kwargs):
        super().__init__(**kwargs)
        self.func = func

    @property
    def desc(self):
        return f"line {self.lineno}: compressed info {self.line!r} passed to {self.func}"


class DoCompressedFilesCheck(Check):
    """Scan ebuild for compressed files passed to ``do*`` or ``new**``."""

    _source = sources.EbuildParseRepoSource
    known_results = frozenset([InstallCompressedManpage, InstallCompressedInfo])

    compresion_extentions = (".Z", ".gz", ".bz2", ".lzma", ".lz", ".lzo", ".lz4", ".xz", ".zst")
    functions = ImmutableDict(
        {
            "doman": InstallCompressedManpage,
            "newman": InstallCompressedManpage,
            "doinfo": InstallCompressedInfo,
        }
    )

    def feed(self, pkg):
        for node in bash.cmd_query.captures(pkg.tree.root_node).get("call", ()):
            call_name = pkg.node_str(node.child_by_field_name("name"))
            if call_name not in self.functions:
                continue
            for arg in node.children[1:]:
                arg_name = pkg.node_str(arg).strip("'\"")
                lineno, _ = arg.start_point
                if arg_name.endswith(self.compresion_extentions):
                    yield self.functions[call_name](
                        call_name, lineno=lineno + 1, line=arg_name, pkg=pkg
                    )


class NonPosixHeadTailUsage(results.LineResult, results.Warning):
    """Using of non-POSIX compliant ``head`` or ``tail``.

    The numeric argument to ``head`` or ``tail`` without ``-n`` (for example
    ``head -10``) is deprecated and not POSIX compliant. To fix, prepand ``-n``
    before the number [#]_.

    .. [#] https://devmanual.gentoo.org/tools-reference/head-and-tail/index.html
    """

    def __init__(self, command, **kwargs):
        super().__init__(**kwargs)
        self.command = command

    @property
    def desc(self):
        return f"line {self.lineno}: non-posix usage of {self.command!r}: {self.line!r}"


class NonConsistentTarUsage(results.LineResult, results.Warning):
    """Using of non-consistent compliant ``tar``.

    The ``tar`` command defaults to reading from stdin, unless this default is
    changed at compile time or the ``TAPE`` environment variable is set.

    To ensure consistent behavior, the ``-f`` or ``--file`` option should
    always be given to ensure the input device is chosen explicitly.
    """

    @property
    def desc(self):
        return f"line {self.lineno}: non-consistent usage of tar without '-f' or '--file': {self.line!r}"


class NonPosixCheck(Check):
    """Scan ebuild for non-posix usage, code which might be not portable."""

    _source = sources.EbuildParseRepoSource
    known_results = frozenset({NonPosixHeadTailUsage, NonConsistentTarUsage})

    def __init__(self, options, **kwargs):
        super().__init__(options, **kwargs)
        self.re_head_tail = re.compile(r"[+-]\d+")

    def check_head_tail(self, pkg, call_node, call_name):
        prev_arg = ""
        for arg in map(pkg.node_str, call_node.children[1:]):
            if self.re_head_tail.match(arg) and not (
                prev_arg.startswith("-") and prev_arg.endswith(("n", "c"))
            ):
                lineno, _ = call_node.start_point
                yield NonPosixHeadTailUsage(
                    f"{call_name} {arg}", lineno=lineno + 1, line=pkg.node_str(call_node), pkg=pkg
                )
                break
            prev_arg = arg

    def check_tar(self, pkg, call_node):
        for idx, arg in enumerate(map(pkg.node_str, call_node.children[1:])):
            if idx == 0 or (arg[:1] == "-" and arg[1:2] != "-"):
                if "f" in arg:
                    return
            elif arg == "--file" or arg.startswith("--file="):
                return
        lineno, _ = call_node.start_point
        yield NonConsistentTarUsage(lineno=lineno + 1, line=pkg.node_str(call_node), pkg=pkg)

    def feed(self, pkg):
        for call_node in bash.cmd_query.captures(pkg.tree.root_node).get("call", ()):
            call_name = pkg.node_str(call_node.child_by_field_name("name"))
            if call_name in ("head", "tail"):
                yield from self.check_head_tail(pkg, call_node, call_name)
            elif call_name == "tar":
                yield from self.check_tar(pkg, call_node)


class GlobDistdir(results.LineResult, results.Warning):
    """Filename expansion with ``${DISTDIR}`` is unsafe.

    Filename expansion could accidentally match irrelevant files in
    ``${DISTDIR}``, e.g. from other packages or other versions of the
    same package.
    """

    @property
    def desc(self):
        return f"line {self.lineno}: unsafe filename expansion used with DISTDIR: {self.line}"


class GlobCheck(Check):
    """Scan ebuilds for unsafe glob usage."""

    _source = sources.EbuildParseRepoSource
    known_results = frozenset({GlobDistdir})

    def __init__(self, options, **kwargs):
        super().__init__(options, **kwargs)
        self.glob_query = bash.query('(concatenation (word) @word (.match? @word "[*?]")) @usage')

    def feed(self, pkg):
        for node in self.glob_query.captures(pkg.tree.root_node).get("usage", ()):
            for var_node in bash.var_query.captures(node).get("var", ()):
                var_name = pkg.node_str(var_node)
                if var_name == "DISTDIR":
                    lineno, _colno = node.start_point
                    yield GlobDistdir(line=pkg.node_str(node), lineno=lineno + 1, pkg=pkg)
                    break


class VariableShadowed(results.LinesResult, results.Warning):
    """Variable is shadowed or repeatedly declared. This is a possible typo."""

    def __init__(self, var_name, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.var_name = var_name

    @property
    def desc(self):
        return f"variable {self.var_name!r} may be shadowed, {self.lines_str}"


class DuplicateFunctionDefinition(results.LinesResult, results.Error):
    """Function is defined multiple times. This is a definetly typo."""

    def __init__(self, func_name, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.func_name = func_name

    @property
    def desc(self):
        return f"multiple definitions of function {self.func_name!r} were found, {self.lines_str}"


class DeclarationShadowedCheck(Check):
    """Scan ebuilds for shadowed variable assignments in global scope."""

    _source = sources.EbuildParseRepoSource
    known_results = frozenset({VariableShadowed, DuplicateFunctionDefinition})

    def feed(self, pkg: bash.ParseTree):
        var_assigns = defaultdict(list)
        func_declares = defaultdict(list)

        for node in pkg.tree.root_node.children:
            if node.type == "variable_assignment":
                used_name = pkg.node_str(node.child_by_field_name("name"))
                if pkg.node_str(node).startswith(used_name + "+="):
                    continue
                if value_node := node.child_by_field_name("value"):
                    if any(
                        pkg.node_str(node) == used_name
                        for node in bash.var_query.captures(value_node).get("var", ())
                    ):
                        continue
                var_assigns[used_name].append(node)
            elif node.type == "function_definition":
                used_name = pkg.node_str(node.child_by_field_name("name"))
                func_declares[used_name].append(node)

        for var_name, nodes in var_assigns.items():
            if len(nodes) > 1:
                lines = sorted(node.start_point[0] + 1 for node in nodes)
                yield VariableShadowed(var_name, lines=lines, pkg=pkg)
        for func_name, nodes in func_declares.items():
            if len(nodes) > 1:
                lines = sorted(node.start_point[0] + 1 for node in nodes)
                yield DuplicateFunctionDefinition(func_name, lines=lines, pkg=pkg)


class InvalidSandboxCall(results.LineResult, results.Error):
    """Invalid call to a sandbox function.

    According to PMS and the Devmanual [#]_, only a single item is allowed as
    argument for ``addread``, ``addwrite``, ``adddeny``, and ``addpredict``.
    Multiple path items should not be passed as a colon-separated list.

    .. [#] https://devmanual.gentoo.org/function-reference/sandbox-functions/
    """

    @property
    def desc(self):
        return f"line {self.lineno}: invalid call to sandbox function: {self.line}"


class SandboxCallCheck(Check):
    """Scan ebuilds for correct sandbox funcitons usage."""

    _source = sources.EbuildParseRepoSource
    known_results = frozenset({InvalidSandboxCall})

    functions = frozenset({"addread", "addwrite", "adddeny", "addpredict"})

    def feed(self, pkg: bash.ParseTree):
        for node in bash.cmd_query.captures(pkg.tree.root_node).get("call", ()):
            name = pkg.node_str(node.child_by_field_name("name"))
            if name in self.functions:
                args = node.children_by_field_name("argument")
                if len(args) != 1 or ":" in pkg.node_str(args[0]):
                    lineno, _ = node.start_point
                    yield InvalidSandboxCall(line=pkg.node_str(node), lineno=lineno + 1, pkg=pkg)


class VariableOrderWrong(results.VersionResult, results.Style):
    """Variable were defined in an unexpected error."""

    def __init__(self, first_var, second_var, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.first_var = first_var
        self.second_var = second_var

    @property
    def desc(self):
        return f"variable {self.first_var} should occur before {self.second_var}"


class VariableOrderCheck(Check):
    """Scan ebuilds for variables defined in a different order than skel.ebuild dictates."""

    _source = sources.EbuildParseRepoSource
    known_results = frozenset({VariableOrderWrong})

    # Order from skel.ebuild
    variable_order = (
        "DESCRIPTION",
        "HOMEPAGE",
        "SRC_URI",
        "S",
        "LICENSE",
        "SLOT",
        "KEYWORDS",
        "IUSE",
        "RESTRICT",
    )

    def feed(self, pkg: bash.ParseTree):
        var_assigns = []

        for node in pkg.tree.root_node.children:
            if node.type == "variable_assignment":
                used_name = pkg.node_str(node.child_by_field_name("name"))
                if used_name in self.variable_order:
                    var_assigns.append(used_name)

        index = 0
        for first_var in var_assigns:
            if first_var in self.variable_order:
                new_index = self.variable_order.index(first_var)
                if new_index < index:
                    yield VariableOrderWrong(first_var, self.variable_order[index], pkg=pkg)
                index = new_index
