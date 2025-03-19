import re
import typing
from collections import defaultdict
from itertools import takewhile
from operator import attrgetter

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
ECLASSES = frozenset(["python-r1", "python-single-r1", "python-any-r1"])

IUSE_PREFIX = "python_targets_"
IUSE_PREFIX_S = "python_single_target_"

GITHUB_ARCHIVE_RE = re.compile(r"^https://github\.com/[^/]+/[^/]+/archive/")
SNAPSHOT_RE = re.compile(r"[a-fA-F0-9]{40}\.tar\.gz$")
PYPI_URI_PREFIX = "https://files.pythonhosted.org/packages/"
PYPI_SDIST_URI_RE = re.compile(
    re.escape(PYPI_URI_PREFIX) + r"source/[^/]/(?P<package>[^/]+)/"
    r"(?P<fn_package>(?P=package)|[^/-]+)-(?P<version>[^/]+)(?P<suffix>\.tar\.gz|\.zip)$"
)
PYPI_WHEEL_URI_RE = re.compile(
    re.escape(PYPI_URI_PREFIX) + r"(?P<pytag>[^/]+)/[^/]/(?P<package>[^/]+)/"
    r"(?P<fn_package>[^/-]+)-(?P<version>[^/-]+)-(?P=pytag)-(?P<abitag>[^/]+)\.whl$"
)
USE_FLAGS_PYTHON_USEDEP = re.compile(r"\[(.+,)?\$\{PYTHON_USEDEP\}(,.+)?\]$")

PROJECT_SYMBOL_NORMALIZE_RE = re.compile(r"[-_.]+")


def get_python_eclass(pkg):
    eclasses = ECLASSES.intersection(pkg.inherited)
    # All three eclasses block one another, but check and throw an error
    # just in case it isn't caught when sourcing the ebuild.
    if len(eclasses) > 1:
        raise ValueError(f"python eclasses are mutually exclusive: [ {', '.join(eclasses)} ]")
    return next(iter(eclasses)) if eclasses else None


def is_python_interpreter(pkg):
    if pkg.key in ("dev-lang/pypy", "dev-lang/python"):
        # ignore python:2.7 deps since they are being phased out from eclass
        # support
        return pkg.slot is None or not pkg.slot.startswith("2")
    return pkg.key in ("dev-python/pypy3",)


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

    desc = 'missing REQUIRED_USE="${PYTHON_REQUIRED_USE}"'


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

    desc = "uses deprecated non-PEP517 build mode, please switch to DISTUTILS_USE_PEP517=..."


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
        return f"usage of has_version {self.lines_str}, replace with python_has_version"


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
        return (
            f"line: {self.lineno}: missing [${{PYTHON_USEDEP}}] suffix for argument {self.line!r}"
        )


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
        use_flags = ", ".join(map(str, self.use_flags))
        return f"{self.dep_category}: mismatch for {self.dep_atom} check use flag{s} [{use_flags}] in {self.location}"


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
        use_flags = ", ".join(map(str, self.use_flags))
        return f"{self.dep_category}: missing check for {self.dep_atom}[{use_flags}] in {self.location!r}"


class PythonMissingSCMDependency(results.VersionResult, results.Warning):
    """Package is missing BDEPEND on setuptools-scm or alike.

    Packages which define ``SETUPTOOLS_SCM_PRETEND_VERSION`` should BDEPEND
    on ``dev-python/setuptools-scm`` or a similar package [#]_.

    .. [#] https://projects.gentoo.org/python/guide/distutils.html#setuptools-scm-flit-scm-hatch-vcs-and-snapshots
    """

    desc = (
        "defines SETUPTOOLS_SCM_PRETEND_VERSION but is missing BDEPEND on setuptools-scm or alike"
    )


class PythonCheck(Check):
    """Python eclass checks.

    Check whether Python eclasses are used for Python packages, and whether
    they don't suffer from common mistakes.
    """

    _source = sources.EbuildParseRepoSource
    known_results = frozenset(
        [
            MissingPythonEclass,
            PythonMissingRequiredUse,
            PythonMissingDeps,
            PythonRuntimeDepInAnyR1,
            PythonEclassError,
            DistutilsNonPEP517Build,
            PythonHasVersionUsage,
            PythonHasVersionMissingPythonUseDep,
            PythonAnyMismatchedUseHasVersionCheck,
            PythonAnyMismatchedDepHasVersionCheck,
            PythonMissingSCMDependency,
        ]
    )

    has_version_known_flags = {
        "-b": "BDEPEND",
        "-r": "RDEPEND",
        "-d": "DEPEND",
        "--host-root": "BDEPEND",
    }

    has_version_default = {
        "has_version": "DEPEND",
        "python_has_version": "BDEPEND",
    }

    eclass_any_dep_func = {
        "python-single-r1": "python_gen_cond_dep",
        "python-any-r1": "python_gen_any_dep",
        "python-r1": "python_gen_any_dep",
    }

    setuptools_scm = frozenset(
        {
            "dev-python/setuptools-scm",
            "dev-python/setuptools_scm",  # legacy old name
            "dev-python/flit-scm",
            "dev-python/flit_scm",  # legacy old name
            "dev-python/hatch-vcs",
        }
    )

    def scan_tree_recursively(self, deptree, expected_cls):
        for x in deptree:
            if not isinstance(x, expected_cls):
                yield from self.scan_tree_recursively(x, expected_cls)
        yield deptree

    def check_required_use(self, requse, flags, prefix, container_cls):
        for token in self.scan_tree_recursively(requse, values.ContainmentMatch2):
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
                    matched.add(name[len(prefix) :])
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
                if not any(is_python_interpreter(y) for y in x if isinstance(y, atom)):
                    continue
                matched.add(flag[len(prefix) :])
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
        uses_setuptools_scm = False
        pep517_value = None

        for var_node in bash.var_assign_query.captures(pkg.tree.root_node).get("assign", ()):
            var_name = pkg.node_str(var_node.child_by_field_name("name"))

            if var_name == "DISTUTILS_OPTIONAL":
                has_distutils_optional = True
            elif var_name == "DISTUTILS_USE_PEP517":
                pep517_value = pkg.node_str(var_node.children[-1])
            elif var_name == "SETUPTOOLS_SCM_PRETEND_VERSION":
                uses_setuptools_scm = True

            if "DISTUTILS_DEPS" in pkg.node_str(var_node.parent):
                # If they're referencing the eclass' dependency variable,
                # there's nothing for us to do anyway.
                has_distutils_deps = True

        bdepends = frozenset(map(attrgetter("key"), iflatten_instance(pkg.bdepend, atom)))

        if pep517_value is None:
            if "dev-python/gpep517" not in bdepends:
                yield DistutilsNonPEP517Build(pkg=pkg)
        elif has_distutils_optional and not has_distutils_deps and pep517_value != "no":
            # We always need BDEPEND for these if != no.
            # We are looking for USE-conditional on appropriate target
            # flag, with dep on dev-python/gpep517.
            if "dev-python/gpep517" not in bdepends:
                yield PythonMissingDeps("BDEPEND", pkg=pkg, dep_value="DISTUTILS_DEPS")

        if uses_setuptools_scm:
            if not self.setuptools_scm.intersection(bdepends):
                yield PythonMissingSCMDependency(pkg=pkg)

    @staticmethod
    def _prepare_deps(deps: str):
        try:
            deps_str = (
                deps.strip("\"'")
                .replace("\\$", "$")
                .replace("${PYTHON_USEDEP}", "pkgcheck_python_usedep")
            )
            return iflatten_instance(DepSet.parse(deps_str, atom), atom)
        except DepsetParseError:
            # if we are unable to parse that dep's string, skip it
            return ()

    def build_python_gen_any_dep_calls(self, pkg, any_dep_func):
        check_deps = defaultdict(set)
        for var_node in pkg.global_query(bash.var_assign_query):
            name = pkg.node_str(var_node.child_by_field_name("name"))
            if name in {"DEPEND", "BDEPEND"}:
                for call_node in bash.cmd_query.captures(var_node).get("call", ()):
                    call_name = pkg.node_str(call_node.child_by_field_name("name"))
                    if call_name == any_dep_func and len(call_node.children) > 1:
                        check_deps[name].update(
                            self._prepare_deps(pkg.node_str(call_node.children[1]))
                        )
        return {dep: frozenset(atoms) for dep, atoms in check_deps.items()}

    def report_mismatch_check_deps(
        self, pkg, python_check_deps, has_version_checked_deps, any_dep_func
    ):
        for dep_type in frozenset(python_check_deps.keys()).union(has_version_checked_deps.keys()):
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
                                yield PythonAnyMismatchedUseHasVersionCheck(
                                    pkg=pkg,
                                    dep_category=dep_type,
                                    dep_atom=dep_atom,
                                    use_flags=diff_flags,
                                    location=location,
                                )
                            break
                    else:
                        use_flags = {"${PYTHON_USEDEP}"} | set(dep.use) - {"pkgcheck_python_usedep"}
                        yield PythonAnyMismatchedDepHasVersionCheck(
                            pkg=pkg,
                            dep_category=dep_type,
                            dep_atom=dep_atom,
                            use_flags=use_flags,
                            location=location,
                        )

    @staticmethod
    def _prepare_dep_type(pkg, dep_type: str) -> str:
        if dep_type == "BDEPEND" not in pkg.eapi.dep_keys:
            return "DEPEND"
        return dep_type

    def check_python_check_deps(self, pkg, func_node, python_check_deps, any_dep_func):
        has_version_checked_deps = defaultdict(set)
        has_version_lines = set()
        for node in bash.cmd_query.captures(func_node).get("call", ()):
            call_name = pkg.node_str(node.child_by_field_name("name"))
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
                        arg_name = arg_name.strip("\"'")
                        if not USE_FLAGS_PYTHON_USEDEP.search(arg_name):
                            lineno, _ = arg.start_point
                            yield PythonHasVersionMissingPythonUseDep(
                                lineno=lineno + 1, line=arg_name, pkg=pkg
                            )
                        else:
                            has_version_checked_deps[dep_mode].update(self._prepare_deps(arg_name))

        if has_version_lines:
            yield PythonHasVersionUsage(lines=sorted(has_version_lines), pkg=pkg)

        yield from self.report_mismatch_check_deps(
            pkg, python_check_deps, has_version_checked_deps, any_dep_func
        )

    def feed(self, pkg):
        try:
            eclass = get_python_eclass(pkg)
        except ValueError as exc:
            yield PythonEclassError(str(exc), pkg=pkg)
            return

        if eclass is None:
            # check whether we should be using one
            highest_found = None
            for attr in (x.lower() for x in pkg.eapi.dep_keys):
                for p in iflatten_instance(getattr(pkg, attr), atom):
                    if not p.blocks and is_python_interpreter(p):
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
        elif eclass in ("python-r1", "python-single-r1"):
            # grab Python implementations from IUSE
            iuse = {x.lstrip("+-") for x in pkg.iuse}

            if eclass == "python-r1":
                flags = {x[len(IUSE_PREFIX) :] for x in iuse if x.startswith(IUSE_PREFIX)}
                req_use_args = (flags, IUSE_PREFIX, OrRestriction)
            else:
                flags = {x[len(IUSE_PREFIX_S) :] for x in iuse if x.startswith(IUSE_PREFIX_S)}
                req_use_args = (flags, IUSE_PREFIX_S, JustOneRestriction)

            if not self.check_required_use(pkg.required_use, *req_use_args):
                yield PythonMissingRequiredUse(pkg=pkg)
            if not self.check_depend(pkg.rdepend, *(req_use_args[:2])):
                yield PythonMissingDeps("RDEPEND", pkg=pkg)
        else:  # python-any-r1
            for attr in ("rdepend", "pdepend"):
                for p in iflatten_instance(getattr(pkg, attr), atom):
                    if not p.blocks and is_python_interpreter(p):
                        yield PythonRuntimeDepInAnyR1(attr.upper(), str(p), pkg=pkg)
                        break
            if not any(
                not p.blocks and is_python_interpreter(p)
                for attr in ("depend", "bdepend")
                for p in iflatten_instance(getattr(pkg, attr), atom)
            ):
                yield PythonMissingDeps("DEPEND", pkg=pkg)

        # We're not interested in testing fake objects from TestPythonCheck
        if (
            eclass is None or not isinstance(pkg, sources._ParsedPkg) or not hasattr(pkg, "tree")
        ):  # pragma: no cover
            return

        if "distutils-r1" in pkg.inherited:
            yield from self.check_pep517(pkg)

        any_dep_func = self.eclass_any_dep_func[eclass]
        python_check_deps = self.build_python_gen_any_dep_calls(pkg, any_dep_func)
        for func_node in bash.func_query.captures(pkg.tree.root_node).get("func", ()):
            func_name = pkg.node_str(func_node.child_by_field_name("name"))
            if func_name == "python_check_deps":
                yield from self.check_python_check_deps(
                    pkg, func_node, python_check_deps, any_dep_func
                )


class PythonCompatUpdate(results.VersionResult, results.Info):
    """``PYTHON_COMPAT`` can be updated to support newer python version(s)."""

    def __init__(self, updates, **kwargs):
        super().__init__(**kwargs)
        self.updates = tuple(updates)

    @property
    def desc(self):
        s = pluralism(self.updates)
        updates = ", ".join(self.updates)
        return f"PYTHON_COMPAT update{s} available: {updates}"


class PythonCompatCheck(Check):
    """Check python ebuilds for possible ``PYTHON_COMPAT`` updates.

    Supports ebuilds inheriting ``python-r1``, ``python-single-r1``, and
    ``python-any-r1``.
    """

    known_results = frozenset({PythonCompatUpdate})

    whitelist_backports = frozenset(
        {
            "dev-python/backports-tarfile",
            "dev-python/exceptiongroup",
            "dev-python/importlib-metadata",
            "dev-python/taskgroup",
            "dev-python/typing-extensions",
            "dev-python/unittest-or-fail",
            "dev-python/zipp",
        }
    )

    def __init__(self, *args):
        super().__init__(*args)
        repo = self.options.target_repo
        # sorter for python targets leveraging USE_EXPAND flag ordering from repo
        self.sorter = repo.use_expand_sorter("python_targets")

        # determine available PYTHON_TARGET use flags
        targets = []
        pypy_targets = []
        for target, _desc in repo.use_expand_desc.get(IUSE_PREFIX[:-1], ()):
            target = target.removeprefix(IUSE_PREFIX)
            if target.startswith("python"):
                targets.append(target)
            elif target.startswith("pypy"):
                pypy_targets.append(target)
        targets = (x for x in targets if not x.endswith("t"))
        multi_targets = tuple(sorted(targets, key=self.sorter))
        self.pypy_targets = tuple(sorted(pypy_targets, key=self.sorter))

        # determine available PYTHON_SINGLE_TARGET use flags
        targets = []
        for target, _desc in repo.use_expand_desc.get(IUSE_PREFIX_S[:-1], ()):
            target = target.removeprefix(IUSE_PREFIX_S)
            if target.startswith("python"):
                targets.append(target)
        targets = (x for x in targets if not x.endswith("t"))
        single_targets = tuple(sorted(targets, key=self.sorter))

        self.params = {
            "python-r1": (multi_targets, IUSE_PREFIX, None),
            "python-single-r1": (single_targets, (IUSE_PREFIX, IUSE_PREFIX_S), None),
            "python-any-r1": (multi_targets, (IUSE_PREFIX, IUSE_PREFIX_S), ("depend", "bdepend")),
        }

    def python_deps(self, deps, prefix):
        for dep in (x for x in deps if x.use):
            for x in dep.use:
                if x.startswith(("-", "!")):
                    continue
                if x.startswith(prefix):
                    yield dep.no_usedeps
                    break

    def deps(self, pkg, attrs=None):
        """Set of dependencies for a given package's attributes."""
        attrs = attrs if attrs is not None else pkg.eapi.dep_keys
        return {
            p
            for attr in (x.lower() for x in attrs)
            for p in iflatten_instance(getattr(pkg, attr), atom)
            if not p.blocks and p.key not in self.whitelist_backports
        }

    def feed(self, pkg):
        try:
            eclass = get_python_eclass(pkg)
            available_targets, prefix, attrs = self.params[eclass]
        except (KeyError, ValueError):
            return

        deps = self.deps(pkg, attrs=attrs)

        try:
            # determine the latest supported python version
            all_targets = (
                f"python{x.slot.replace('.', '_')}"
                for x in deps
                if x.key == "dev-lang/python" and x.slot is not None and not x.slot.endswith("t")
            )
            latest_target = max(all_targets, key=self.sorter)
        except ValueError:
            # should be flagged by PythonMissingDeps
            return

        # ignore pkgs that probably aren't py3 compatible
        if latest_target == "python2_7":
            return

        # determine python impls to target
        targets = set(takewhile(lambda x: x != latest_target, reversed(available_targets)))

        try:
            # determine the latest supported pypy version
            all_targets = (
                "pypy3" if x.slot == "3.10" else f"pypy{x.slot.replace('.', '_')}"
                for x in deps
                if x.key == "dev-lang/pypy" and x.slot is not None
            )
            latest_pypy = max(all_targets, key=self.sorter)
            targets.update(takewhile(lambda x: x != latest_pypy, reversed(self.pypy_targets)))
        except ValueError:
            ...

        if targets:
            try:
                # determine if deps support missing python targets
                for dep in self.python_deps(deps, prefix):
                    # TODO: use query caching for repo matching?
                    latest = sorted(self.options.search_repo.match(dep))[-1]
                    targets.intersection_update(
                        (
                            f"pypy{x.rsplit('pypy', 1)[-1]}"
                            if "pypy" in x
                            else f"python{x.rsplit('python', 1)[-1]}"
                        )
                        for x in latest.iuse_stripped
                        if x.startswith(prefix)
                    )
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

    To solve this warning, rename the distfile in ``SRC_URI`` to include the
    suffix. There is no need to contact upstream, as it is done simply by
    adding ``-> ${P}.gh.tar.gz`` after the URI.
    """

    def __init__(self, filename, uri, **kwargs):
        super().__init__(**kwargs)
        self.filename = filename
        self.uri = uri

    @property
    def desc(self):
        return (
            f"GitHub archive {self.filename!r} ({self.uri!r}) is not " "using '.gh.tar.gz' suffix"
        )


class PythonInlinePyPIURI(results.VersionResult, results.Warning):
    """PyPI URI used inline instead of via pypi.eclass"""

    def __init__(
        self,
        url: str,
        replacement: typing.Optional[tuple[str, ...]] = None,
        normalize: typing.Optional[bool] = None,
        append: typing.Optional[bool] = None,
        pypi_pn: typing.Optional[str] = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.url = url
        self.replacement = tuple(replacement) if replacement is not None else None
        self.normalize = normalize
        self.append = append
        self.pypi_pn = pypi_pn

    @property
    def desc(self) -> str:
        if self.replacement is None:
            no_norm = "" if self.normalize else "set PYPI_NO_NORMALIZE=1, "
            pypi_pn = "" if self.pypi_pn is None else f"set PYPI_PN={self.pypi_pn}, "
            final = "use SRC_URI+= for other URIs" if self.append else "remove SRC_URI"
            return (
                "inline PyPI URI found matching pypi.eclass default, inherit the eclass, "
                f"{no_norm}{pypi_pn}and {final} instead"
            )
        else:
            return (
                f"inline PyPI URI found: {self.url}, inherit pypi.eclass and replace with "
                f"$({' '.join(self.replacement)})"
            )


class PythonFetchableCheck(Check):
    """Perform Python-specific checks to fetchables."""

    required_addons = (addons.UseAddon,)
    known_results = frozenset({PythonGHDistfileSuffix, PythonInlinePyPIURI})

    def __init__(self, *args, use_addon):
        super().__init__(*args)
        self.iuse_filter = use_addon.get_filter("fetchables")

    def check_gh_suffix(self, pkg, fetchables):
        # consider only packages with pypi remote-id
        if not any(u.type == "pypi" for u in pkg.upstreams):
            return

        # look for GitHub archives
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

    @staticmethod
    def simplify_pn_pv(pn: str, pv: str, pkg, allow_none: bool) -> tuple[str, str]:
        if pv == pkg.version:
            pv = None if allow_none else '"${PV}"'

        if pn == pkg.package:
            pn = None if pv is None else '"${PN}"'
        # check for common PN transforms that conform to naming policy
        elif pn == pkg.package.replace("-", ".", 1):
            pn = '"${PN/-/.}"'
        elif pn == pkg.package.replace("-", "."):
            pn = '"${PN//-/.}"'
        elif pn == pkg.package.replace("-", "_", 1):
            pn = '"${PN/-/_}"'
        elif pn == pkg.package.replace("-", "_"):
            pn = '"${PN//-/_}"'
        # .title() is not exactly the same as ^
        elif pn == f"{pkg.package[:1].upper()}{pkg.package[1:]}":
            pn = '"${PN^}"'

        return pn, pv

    @staticmethod
    def normalize_distribution_name(name: str) -> str:
        """Normalize the distribution according to sdist/wheel spec"""
        return PROJECT_SYMBOL_NORMALIZE_RE.sub("_", name).lower()

    @staticmethod
    def translate_version(version: str) -> str:
        """Translate Gentoo version into PEP 440 version"""
        return (
            version.replace("_alpha", "a")
            .replace("_beta", "b")
            .replace("_rc", "rc")
            .replace("_p", ".post")
        )

    def check_pypi_mirror(self, pkg, fetchables):
        # consider only packages that don't inherit pypi.eclass already
        if "pypi" in pkg.inherited:
            return

        uris = [(uri, f.filename) for f in fetchables for uri in f.uri]
        # check if we have any mirror://pypi URLs in the first place
        pypi_uris = [uri for uri in uris if uri[0].startswith(PYPI_URI_PREFIX)]
        if not pypi_uris:
            return

        # if there's exactly one PyPI URI, perhaps inheriting the eclass will suffice
        if len(pypi_uris) == 1:
            uri, filename = pypi_uris[0]

            if source_match := PYPI_SDIST_URI_RE.match(uri):
                pn, filename_pn, pv, suffix = source_match.groups()
                translated_version = self.translate_version(pkg.version)
                if (
                    pv == translated_version
                    and suffix == ".tar.gz"
                    and filename == f"{filename_pn}-{translated_version}.tar.gz"
                ):
                    append = len(uris) > 1
                    normalize = filename_pn == self.normalize_distribution_name(pn)
                    if not normalize and filename_pn != pn:
                        # ignore malformed URLs
                        return
                    pn, _ = self.simplify_pn_pv(pn, None, pkg, True)
                    yield PythonInlinePyPIURI(
                        uri, normalize=normalize, append=append, pypi_pn=pn, pkg=pkg
                    )
                    return

        # otherwise, yield result for every URL, with suggested replacement
        for uri, dist_filename in pypi_uris:
            if source_match := PYPI_SDIST_URI_RE.match(uri):
                pn, filename_pn, pv, suffix = source_match.groups()

                if filename_pn == self.normalize_distribution_name(pn):
                    no_normalize_arg = None
                elif filename_pn == pn:
                    no_normalize_arg = "--no-normalize"
                else:  # incorrect project name?
                    continue
                if suffix == ".tar.gz":
                    suffix = None
                pn, pv = self.simplify_pn_pv(pn, pv, pkg, suffix is None)

                args = tuple(filter(None, ("pypi_sdist_url", no_normalize_arg, pn, pv, suffix)))
                yield PythonInlinePyPIURI(uri, args, pkg=pkg)
                continue

            if wheel_match := PYPI_WHEEL_URI_RE.match(uri):
                pytag, pn, filename_pn, pv, abitag = wheel_match.groups()
                unpack_arg = None

                # only normalized wheel names are supported
                if filename_pn != self.normalize_distribution_name(pn):
                    return
                if dist_filename in (
                    f"{filename_pn}-{pv}-{pytag}-{abitag}.whl.zip",
                    f"{filename_pn}-{pv}-{pytag}-{abitag}.zip",
                ):
                    unpack_arg = "--unpack"
                if abitag == "none-any":
                    abitag = None
                if pytag == "py3" and abitag is None:
                    pytag = None
                pn, pv = self.simplify_pn_pv(pn, pv, pkg, abitag is None)

                args = tuple(filter(None, ("pypi_wheel_url", unpack_arg, pn, pv, pytag, abitag)))
                yield PythonInlinePyPIURI(uri, args, pkg=pkg)

    def feed(self, pkg):
        fetchables, _ = self.iuse_filter(
            (fetch.fetchable,),
            pkg,
            pkg.generate_fetchables(
                allow_missing_checksums=True, ignore_unknown_mirrors=True, skip_default_mirrors=True
            ),
        )

        yield from self.check_gh_suffix(pkg, fetchables)
        yield from self.check_pypi_mirror(pkg, fetchables)


class PythonMismatchedPackageName(results.PackageResult, results.Info):
    """Package name does not follow PyPI-based naming policy.

    All packages in ``dev-python/*`` that are published on PyPI, must be named to
    match their respective PyPI names [#]_.

    .. [#] https://projects.gentoo.org/python/guide/package-maintenance.html#package-name-policy
    """

    def __init__(self, recommended: str, **kwargs):
        super().__init__(**kwargs)
        self.recommended = recommended

    @property
    def desc(self) -> str:
        return f"package name does not match remote-id, recommended name: {self.recommended!r}"


class PythonPackageNameCheck(Check):
    """Check ebuild names in dev-python/*."""

    _source = sources.PackageRepoSource
    known_results = frozenset([PythonMismatchedPackageName])

    def feed(self, pkgs):
        pkg = next(iter(pkgs))

        # the policy applies to dev-python/* only
        if pkg.category != "dev-python":
            return

        # consider only packages with a single pypi remote-id
        pypi_remotes = [x for x in pkg.upstreams if x.type == "pypi"]
        if len(pypi_remotes) != 1:
            return

        def normalize(project: str) -> str:
            """
            Normalize project name using PEP 503 rules

            https://peps.python.org/pep-0503/#normalized-names
            """
            return PROJECT_SYMBOL_NORMALIZE_RE.sub("-", project).lower()

        pypi_name = pypi_remotes[0].name
        if pkg.package != normalize(pypi_name):
            yield PythonMismatchedPackageName(normalize(pypi_name), pkg=pkg)
