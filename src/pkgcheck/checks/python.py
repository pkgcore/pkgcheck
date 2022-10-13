from collections import defaultdict
import itertools
import re

from pkgcore import fetch
from pkgcore.ebuild.atom import atom
from pkgcore.ebuild.conditionals import DepSet
from pkgcore.ebuild.errors import DepsetParseError
from pkgcore.restrictions import packages, values
from pkgcore.restrictions.boolean import JustOneRestriction, OrRestriction
from snakeoil.sequences import iflatten_instance
from snakeoil.strings import pluralism

from .. import addons, bash, results, sources
from . import Check

# NB: distutils-r1 inherits one of the first two
ECLASSES = frozenset(['python-r1', 'python-single-r1', 'python-any-r1'])

# NB: dev-java/jython omitted as not supported by the eclasses atm
INTERPRETERS = frozenset([
    'dev-lang/python',
    'dev-python/pypy',
    'dev-python/pypy3',
    'dev-python/pypy-bin',
    'dev-python/pypy3-bin',
    'virtual/pypy',
    'virtual/pypy3',
])

CHECK_EXCLUDE = frozenset(['virtual/pypy', 'virtual/pypy3'])

IUSE_PREFIX = 'python_targets_'
IUSE_PREFIX_S = 'python_single_target_'

GITHUB_ARCHIVE_RE = re.compile(r'^https://github\.com/[^/]+/[^/]+/archive/')
SNAPSHOT_RE = re.compile(r'[a-fA-F0-9]{40}\.tar\.gz$')
USE_FLAGS_PYTHON_USEDEP = re.compile(r'\[(.+,)?\$\{PYTHON_USEDEP\}(,.+)?\]$')


def get_python_eclass(pkg):
    eclasses = ECLASSES.intersection(pkg.inherited)
    # All three eclasses block one another, but check and throw an error
    # just in case it isn't caught when sourcing the ebuild.
    if len(eclasses) > 1:
        raise ValueError(
            f"python eclasses are mutually exclusive: [ {', '.join(eclasses)} ]")
    return next(iter(eclasses)) if eclasses else None


class MissingPythonEclass(results.VersionResult, results.Warning):
    """Package depends on Python but does not use the eclasses.

    All packages depending on Python are required to use one of the following
    python eclasses: ``python-r1``, ``python-single-r1``, or ``python-any-r1``.
    For documentation on choosing the correct eclass, please see the Gentoo
    Python Guide page on eclasses [#]_.

    .. [#] https://projects.gentoo.org/python/guide/eclass.html
    """

    def __init__(self, eclass, dep_type, dep, **kwargs):
        super().__init__(**kwargs)
        self.eclass = eclass
        self.dep_type = dep_type
        self.dep = dep

    @property
    def desc(self):
        return f'missing {self.eclass} eclass usage for {self.dep_type}="{self.dep}"'


class PythonMissingRequiredUse(results.VersionResult, results.Warning):
    """Package is missing ``PYTHON_REQUIRED_USE``.

    The ``python-r1`` and ``python-single-r1`` eclasses require the packages to
    explicitly specify ``REQUIRED_USE=${PYTHON_REQUIRED_USE}``. If Python is
    used conditionally, it can be wrapped in appropriate USE conditionals.
    """

    @property
    def desc(self):
        return 'missing REQUIRED_USE="${PYTHON_REQUIRED_USE}"'


class PythonMissingDeps(results.VersionResult, results.Warning):
    """Package is missing ``PYTHON_DEPS``.

    The ``python-r1`` and ``python-single-r1`` eclasses require the packages
    to explicitly reference ``${PYTHON_DEPS}`` in ``RDEPEND`` (and ``DEPEND``,
    if necessary); ``python-any-r1`` requires it in ``DEPEND``.

    If Python is used conditionally, the dependency can be wrapped
    in appropriate USE conditionals.
    """

    def __init__(self, dep_type, dep_value="PYTHON_DEPS", **kwargs):
        super().__init__(**kwargs)
        self.dep_type = dep_type
        self.dep_value = dep_value

    @property
    def desc(self):
        return f'missing {self.dep_type}="${{{self.dep_value}}}"'


class PythonRuntimeDepInAnyR1(results.VersionResult, results.Warning):
    """Package depends on Python at runtime but uses any-r1 eclass.

    The ``python-any-r1`` eclass is meant to be used purely for build-time
    dependencies on Python. However, this package lists Python as a runtime
    dependency. If this is intentional, the package needs to switch to
    ``python-r1`` or ``python-single-r1`` eclass, otherwise the runtime
    dependency should be removed.
    """

    def __init__(self, dep_type, dep, **kwargs):
        super().__init__(**kwargs)
        self.dep_type = dep_type
        self.dep = dep

    @property
    def desc(self):
        return (
            f'inherits python-any-r1 with {self.dep_type}="{self.dep}" -- '
            "use python-r1 or python-single-r1 instead"
        )


class PythonEclassError(results.VersionResult, results.Error):
    """Generic python eclass error."""

    def __init__(self, msg, **kwargs):
        super().__init__(**kwargs)
        self.msg = msg

    @property
    def desc(self):
        return self.msg


class DistutilsNonPEP517Build(results.VersionResult, results.Warning):
    """Ebuild uses the deprecated non-PEP517 build"""

    @property
    def desc(self):
        return (
            "uses deprecated non-PEP517 build mode, please switch to "
            "DISTUTILS_USE_PEP517=..."
        )


class PythonHasVersionUsage(results.LinesResult, results.Style):
    """Package uses has_version inside ``python_check_deps``.

    Ebuilds which declare the ``python_check_deps`` function (which tests
    Python implementations for matching dependencies) should use the special
    ``python_has_version`` function (instead of ``has_version``) for enhanced
    log output and defaults [#]_.

    .. [#] https://projects.gentoo.org/python/guide/any.html#dependencies
    """

    @property
    def desc(self):
        return f'usage of has_version {self.lines_str}, replace with python_has_version'


class PythonHasVersionMissingPythonUseDep(results.LineResult, results.Error):
    """Package calls ``python_has_version`` or ``has_version`` without
    ``[${PYTHON_USEDEP}]`` suffix.

    All calls  to ``python_has_version`` or ``has_version`` inside
    ``python_check_deps`` should contain ``[${PYTHON_USEDEP}]`` suffix for the
    dependency argument [#]_.

    .. [#] https://projects.gentoo.org/python/guide/any.html#dependencies
    """

    @property
    def desc(self):
        return f'line: {self.lineno}: missing [${{PYTHON_USEDEP}}] suffix for argument "{self.line}"'


class PythonAnyMismatchedUseHasVersionCheck(results.VersionResult, results.Warning):
    """Package has mismatch in dependency's use flags between call to
    ``python_gen_any_dep`` and ``python_has_version``.

    For every dependency used under ``python_gen_any_dep``, the check for a
    matching python implementation in ``python_has_version`` should match the
    exact use flags [#]_.

    .. [#] https://projects.gentoo.org/python/guide/any.html#dependencies
    """

    def __init__(self, dep_category, dep_atom, use_flags, location, **kwargs):
        super().__init__(**kwargs)
        self.dep_category = dep_category
        self.dep_atom = dep_atom
        self.use_flags = tuple(use_flags)
        self.location = location

    @property
    def desc(self):
        s = pluralism(self.use_flags)
        use_flags = ', '.join(map(str, self.use_flags))
        return f'{self.dep_category}: mismatch for {self.dep_atom} check use flag{s} [{use_flags}] in {self.location}'


class PythonAnyMismatchedDepHasVersionCheck(results.VersionResult, results.Warning):
    """Package has mismatch in dependencies between call to
    ``python_gen_any_dep`` and ``python_has_version``.

    For every dependency used under ``python_gen_any_dep``, a matching check
    for a matching python implementation in ``python_has_version`` should
    exist [#]_.

    .. [#] https://projects.gentoo.org/python/guide/any.html#dependencies
    """

    def __init__(self, dep_category, dep_atom, use_flags, location, **kwargs):
        super().__init__(**kwargs)
        self.dep_category = dep_category
        self.dep_atom = dep_atom
        self.use_flags = tuple(use_flags)
        self.location = location

    @property
    def desc(self):
        use_flags = ', '.join(map(str, self.use_flags))
        return f'{self.dep_category}: missing check for {self.dep_atom}[{use_flags}] in {self.location!r}'

class PythonCheck(Check):
    """Python eclass checks.

    Check whether Python eclasses are used for Python packages, and whether
    they don't suffer from common mistakes.
    """

    _source = sources.EbuildParseRepoSource
    known_results = frozenset([
        MissingPythonEclass, PythonMissingRequiredUse,
        PythonMissingDeps, PythonRuntimeDepInAnyR1, PythonEclassError,
        DistutilsNonPEP517Build,
        PythonHasVersionUsage,
        PythonHasVersionMissingPythonUseDep,
        PythonAnyMismatchedUseHasVersionCheck,
        PythonAnyMismatchedDepHasVersionCheck,
    ])

    has_version_known_flags = {
        '-b': 'BDEPEND',
        '-r': 'RDEPEND',
        '-d': 'DEPEND',
        '--host-root': 'BDEPEND',
    }

    has_version_default = {
        'has_version': 'DEPEND',
        'python_has_version': 'BDEPEND',
    }

    eclass_any_dep_func = {
        'python-single-r1': 'python_gen_cond_dep',
        'python-any-r1': 'python_gen_any_dep',
        'python-r1': 'python_gen_any_dep',
    }

    def scan_tree_recursively(self, deptree, expected_cls):
        for x in deptree:
            if not isinstance(x, expected_cls):
                for y in self.scan_tree_recursively(x, expected_cls):
                    yield y
        yield deptree

    def check_required_use(self, requse, flags, prefix, container_cls):
        for token in self.scan_tree_recursively(requse,
                                                values.ContainmentMatch2):
            # pkgcore collapses single flag in ||/^^, so expect top-level flags
            # when len(flags) == 1
            if len(flags) > 1 and not isinstance(token, container_cls):
                continue
            matched = set()
            for x in token:
                if not isinstance(x, values.ContainmentMatch2):
                    continue
                name = next(iter(x.vals))
                if name.startswith(prefix):
                    matched.add(name[len(prefix):])
                elif isinstance(token, container_cls):
                    # skip the ||/^^ if it contains at least one foreign flag
                    break
            else:
                if flags == matched:
                    # we found PYTHON_REQUIRED_USE, terminate
                    return True
        return False

    def check_depend(self, depend, flags, prefix):
        for token in self.scan_tree_recursively(depend, atom):
            matched = set()
            for x in token:
                # we are looking for USE-conditional on appropriate target
                # flag, with dep on some interpreter
                if not isinstance(x, packages.Conditional):
                    continue
                flag = next(iter(x.restriction.vals))
                if not flag.startswith(prefix):
                    continue
                if not any(y.key in INTERPRETERS for y in x if isinstance(y, atom)):
                    continue
                matched.add(flag[len(prefix):])
            if matched == flags:
                return True
        return False

    def check_pep517(self, pkg):
        """Check Python ebuilds for whether PEP517 mode is used and missing
        optional dependencies.

        The problematic case for us is ``DISTUTILS_OPTIONAL`` and
        ``DISTUTILS_USE_PEP517 != no`` but ``${DISTUTILS_DEPS}`` is not in
        the ebuild.
        """
        has_distutils_optional = None
        has_distutils_deps = False
        pep517_value = None

        for var_node, _ in bash.var_assign_query.captures(pkg.tree.root_node):
            var_name = pkg.node_str(var_node.child_by_field_name('name'))

            if var_name == "DISTUTILS_OPTIONAL":
                has_distutils_optional = True
            elif var_name == "DISTUTILS_USE_PEP517":
                pep517_value = pkg.node_str(var_node.children[-1])

            if "DISTUTILS_DEPS" in pkg.node_str(var_node.parent):
                # If they're referencing the eclass' dependency variable,
                # there's nothing for us to do anyway.
                has_distutils_deps = True


        if pep517_value is None:
            yield DistutilsNonPEP517Build(pkg=pkg)
        elif has_distutils_optional and not has_distutils_deps and pep517_value != "no":
            # We always need BDEPEND for these if != no.
            # We are looking for USE-conditional on appropriate target
            # flag, with dep on dev-python/gpep517.
            if "dev-python/gpep517" not in iflatten_instance(pkg.bdepend, atom):
                yield PythonMissingDeps("BDEPEND", pkg=pkg, dep_value="DISTUTILS_DEPS")


    @staticmethod
    def _prepare_deps(deps: str):
        try:
            deps_str = deps.strip('\"\'').replace('\\$', '$').replace('${PYTHON_USEDEP}', 'pkgcheck_python_usedep')
            return iflatten_instance(DepSet.parse(deps_str, atom), atom)
        except DepsetParseError:
            # if we are unable to parse that dep's string, skip it
            return ()

    def build_python_gen_any_dep_calls(self, pkg, any_dep_func):
        check_deps = defaultdict(set)
        for var_node in pkg.global_query(bash.var_assign_query):
            name = pkg.node_str(var_node.child_by_field_name('name'))
            if name in {'DEPEND', 'BDEPEND'}:
                for call_node, _ in bash.cmd_query.captures(var_node):
                    call_name = pkg.node_str(call_node.child_by_field_name('name'))
                    if call_name == any_dep_func and len(call_node.children) > 1:
                        check_deps[name].update(self._prepare_deps(
                            pkg.node_str(call_node.children[1])))
        return {dep: frozenset(atoms) for dep, atoms in check_deps.items()}

    def report_mismatch_check_deps(self, pkg, python_check_deps, has_version_checked_deps, any_dep_func):
        for dep_type in frozenset(python_check_deps.keys()).union(
                has_version_checked_deps.keys()):
            extra = has_version_checked_deps[dep_type] - python_check_deps.get(dep_type, set())
            missing = python_check_deps.get(dep_type, set()) - has_version_checked_deps[dep_type]
            for diff, other, location in (
                (extra, missing, any_dep_func),
                (missing, extra, "python_check_deps"),
            ):
                for dep in diff:
                    dep_atom = str(dep.versioned_atom)
                    for other_dep in other:
                        if dep_atom == str(other_dep.versioned_atom):
                            if diff_flags := set(other_dep.use) - set(dep.use):
                                yield PythonAnyMismatchedUseHasVersionCheck(pkg=pkg,
                                    dep_category=dep_type, dep_atom=dep_atom,
                                    use_flags=diff_flags, location=location)
                            break
                    else:
                        use_flags = {'${PYTHON_USEDEP}'} | set(dep.use) \
                           - {'pkgcheck_python_usedep'}
                        yield PythonAnyMismatchedDepHasVersionCheck(pkg=pkg,
                            dep_category=dep_type, dep_atom=dep_atom,
                            use_flags=use_flags, location=location)

    @staticmethod
    def _prepare_dep_type(pkg, dep_type: str) -> str:
        if dep_type == 'BDEPEND' not in pkg.eapi.dep_keys:
            return 'DEPEND'
        return dep_type

    def check_python_check_deps(self, pkg, func_node, python_check_deps, any_dep_func):
        has_version_checked_deps = defaultdict(set)
        has_version_lines = set()
        for node, _ in bash.cmd_query.captures(func_node):
            call_name = pkg.node_str(node.child_by_field_name('name'))
            if call_name == "has_version":
                lineno, _ = node.start_point
                has_version_lines.add(lineno + 1)
            if dep_mode := self.has_version_default.get(call_name, None):
                dep_mode = self._prepare_dep_type(pkg, dep_mode)
                for arg in node.children[1:]:
                    arg_name = pkg.node_str(arg)
                    if new_dep_mode := self.has_version_known_flags.get(arg_name, None):
                        dep_mode = self._prepare_dep_type(pkg, new_dep_mode)
                    else:
                        arg_name = arg_name.strip('\"\'')
                        if not USE_FLAGS_PYTHON_USEDEP.search(arg_name):
                            lineno, _ = arg.start_point
                            yield PythonHasVersionMissingPythonUseDep(
                                lineno=lineno+1, line=arg_name, pkg=pkg)
                        else:
                            has_version_checked_deps[dep_mode].update(
                                self._prepare_deps(arg_name))

        if has_version_lines:
            yield PythonHasVersionUsage(lines=sorted(has_version_lines), pkg=pkg)

        yield from self.report_mismatch_check_deps(pkg, python_check_deps, has_version_checked_deps, any_dep_func)

    def feed(self, pkg):
        try:
            eclass = get_python_eclass(pkg)
        except ValueError as exc:
            yield PythonEclassError(str(exc), pkg=pkg)
            return

        if eclass is None:
            # virtual/pypy* need to be exempted as they serve as slot-matchers
            # for other packages
            if pkg.key in CHECK_EXCLUDE:
                return

            # check whether we should be using one
            highest_found = None
            for attr in (x.lower() for x in pkg.eapi.dep_keys):
                for p in iflatten_instance(getattr(pkg, attr), atom):
                    if not p.blocks and p.key in INTERPRETERS:
                        highest_found = (attr, p)
                        # break scanning packages, go to next attr
                        break

            if highest_found is not None:
                attr, p = highest_found
                if attr in ("rdepend", "pdepend"):
                    recommendation = "python-r1 or python-single-r1"
                else:
                    recommendation = "python-any-r1"
                yield MissingPythonEclass(recommendation, attr.upper(), str(p), pkg=pkg)
        elif eclass in ('python-r1', 'python-single-r1'):
            # grab Python implementations from IUSE
            iuse = {x.lstrip('+-') for x in pkg.iuse}

            if eclass == 'python-r1':
                flags = {x[len(IUSE_PREFIX):] for x in iuse if x.startswith(IUSE_PREFIX)}
                req_use_args = (flags, IUSE_PREFIX, OrRestriction)
            else:
                flags = {x[len(IUSE_PREFIX_S):] for x in iuse if x.startswith(IUSE_PREFIX_S)}
                req_use_args = (flags, IUSE_PREFIX_S, JustOneRestriction)

            if not self.check_required_use(pkg.required_use, *req_use_args):
                yield PythonMissingRequiredUse(pkg=pkg)
            if not self.check_depend(pkg.rdepend, *(req_use_args[:2])):
                yield PythonMissingDeps('RDEPEND', pkg=pkg)
        else:  # python-any-r1
            for attr in ("rdepend", "pdepend"):
                for p in iflatten_instance(getattr(pkg, attr), atom):
                    if not p.blocks and p.key in INTERPRETERS:
                        yield PythonRuntimeDepInAnyR1(attr.upper(), str(p), pkg=pkg)
                        break
            if not any(
                not p.blocks and p.key in INTERPRETERS
                for attr in ("depend", "bdepend")
                for p in iflatten_instance(getattr(pkg, attr), atom)
            ):
                yield PythonMissingDeps('DEPEND', pkg=pkg)

        # We're not interested in testing fake objects from TestPythonCheck
        if eclass is None or not isinstance(pkg, sources._ParsedPkg) or not hasattr(pkg, 'tree'): # pragma: no cover
            return

        if "distutils-r1" in pkg.inherited:
            yield from self.check_pep517(pkg)

        any_dep_func = self.eclass_any_dep_func[eclass]
        python_check_deps = self.build_python_gen_any_dep_calls(pkg, any_dep_func)
        for func_node, _ in bash.func_query.captures(pkg.tree.root_node):
            func_name = pkg.node_str(func_node.child_by_field_name('name'))
            if func_name == "python_check_deps":
                yield from self.check_python_check_deps(pkg, func_node, python_check_deps, any_dep_func)


class PythonCompatUpdate(results.VersionResult, results.Info):
    """``PYTHON_COMPAT`` can be updated to support newer python version(s)."""

    def __init__(self, updates, **kwargs):
        super().__init__(**kwargs)
        self.updates = tuple(updates)

    @property
    def desc(self):
        s = pluralism(self.updates)
        updates = ', '.join(self.updates)
        return f'PYTHON_COMPAT update{s} available: {updates}'


class PythonCompatCheck(Check):
    """Check python ebuilds for possible ``PYTHON_COMPAT`` updates.

    Supports ebuilds inheriting ``python-r1``, ``python-single-r1``, and
    ``python-any-r1``.
    """

    known_results = frozenset([PythonCompatUpdate])

    def __init__(self, *args):
        super().__init__(*args)
        repo = self.options.target_repo
        # sorter for python targets leveraging USE_EXPAND flag ordering from repo
        self.sorter = repo.use_expand_sorter('python_targets')

        # determine available PYTHON_TARGET use flags
        targets = []
        for target, _desc in repo.use_expand_desc.get(IUSE_PREFIX[:-1], ()):
            if target[len(IUSE_PREFIX):].startswith('python'):
                targets.append(target[len(IUSE_PREFIX):])
        multi_targets = tuple(sorted(targets, key=self.sorter))

        # determine available PYTHON_SINGLE_TARGET use flags
        targets = []
        for target, _desc in repo.use_expand_desc.get(IUSE_PREFIX_S[:-1], ()):
            if target[len(IUSE_PREFIX_S):].startswith('python'):
                targets.append(target[len(IUSE_PREFIX_S):])
        single_targets = tuple(sorted(targets, key=self.sorter))

        self.params = {
            'python-r1': (multi_targets, IUSE_PREFIX, None),
            'python-single-r1': (single_targets, (IUSE_PREFIX, IUSE_PREFIX_S), None),
            'python-any-r1': (multi_targets, (IUSE_PREFIX, IUSE_PREFIX_S), ('depend', 'bdepend')),
        }

    def python_deps(self, deps, prefix):
        for dep in (x for x in deps if x.use):
            for x in dep.use:
                if x.startswith(('-', '!')):
                    continue
                if x.startswith(prefix):
                    yield dep.no_usedeps
                    break

    def deps(self, pkg, attrs=None):
        """Set of dependencies for a given package's attributes."""
        attrs = attrs if attrs is not None else pkg.eapi.dep_keys
        deps = set()
        for attr in (x.lower() for x in attrs):
            for p in iflatten_instance(getattr(pkg, attr), atom):
                if not p.blocks:
                    deps.add(p)
        return deps

    def feed(self, pkg):
        try:
            eclass = get_python_eclass(pkg)
            available_targets, prefix, attrs = self.params[eclass]
        except (KeyError, ValueError):
            return

        deps = self.deps(pkg, attrs=attrs)

        try:
            # determine the latest supported python version
            latest_target = sorted(
                (f"python{x.slot.replace('.', '_')}" for x in deps
                if x.key == 'dev-lang/python' and x.slot is not None), key=self.sorter)[-1]
        except IndexError:
            # should be flagged by PythonMissingDeps
            return

        # ignore pkgs that probably aren't py3 compatible
        if latest_target == 'python2_7':
            return

        # determine python impls to target
        targets = set(itertools.takewhile(
            lambda x: x != latest_target, reversed(available_targets)))

        if targets:
            try:
                # determine if deps support missing python targets
                for dep in self.python_deps(deps, prefix):
                    # TODO: use query caching for repo matching?
                    latest = sorted(self.options.search_repo.match(dep))[-1]
                    targets.intersection_update(
                        f"python{x.rsplit('python', 1)[-1]}"
                        for x in latest.iuse_stripped if x.startswith(prefix))
                    if not targets:
                        return
            except IndexError:
                return

            yield PythonCompatUpdate(sorted(targets, key=self.sorter), pkg=pkg)


class PythonGHDistfileSuffix(results.VersionResult, results.Warning):
    """Distfile from GitHub is missing ".gh.tar.gz" suffix.

    Python ebuilds frequently prefer GitHub archives over sdist tarballs
    published on PyPI.  Since both kinds of distfiles often have the same name,
    ".gh.tar.gz" suffix is often used for the former to avoid filename
    collisions with official archives published upstream.
    """

    def __init__(self, filename, uri, **kwargs):
        super().__init__(**kwargs)
        self.filename = filename
        self.uri = uri

    @property
    def desc(self):
        return (f"GitHub archive {self.filename!r} ({self.uri!r}) is not "
                "using '.gh.tar.gz' suffix")


class PythonGHDistfileSuffixCheck(Check):
    """Check ebuilds with PyPI remotes for missing ".gh.tar.gz" suffixes.
    """

    required_addons = (addons.UseAddon,)
    known_results = frozenset([PythonGHDistfileSuffix])

    def __init__(self, *args, use_addon):
        super().__init__(*args)
        self.iuse_filter = use_addon.get_filter('fetchables')

    def feed(self, pkg):
        # consider only packages with pypi remote-id
        if not any(u.type == "pypi" for u in pkg.upstreams):
            return

        # look for GitHub archives
        fetchables, _ = self.iuse_filter(
            (fetch.fetchable,), pkg,
            pkg.generate_fetchables(allow_missing_checksums=True,
                                    ignore_unknown_mirrors=True,
                                    skip_default_mirrors=True))
        for f in fetchables:
            # skip files that have the correct suffix already
            if f.filename.endswith(".gh.tar.gz"):
                continue
            # skip other files
            if not f.filename.endswith(".tar.gz"):
                continue
            # skip files with explicit hash-suffix
            if SNAPSHOT_RE.search(f.filename):
                continue
            for uri in f.uri:
                if GITHUB_ARCHIVE_RE.match(uri):
                    yield PythonGHDistfileSuffix(f.filename, uri, pkg=pkg)
                    break
