from pkgcore.ebuild.atom import atom
from pkgcore.restrictions import packages, values
from pkgcore.restrictions.boolean import JustOneRestriction, OrRestriction
from snakeoil.sequences import iflatten_instance

from .. import results
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


class MissingPythonEclass(results.VersionedResult, results.Warning):
    """Package depends on Python but does not use the eclasses.

    All packages depending on Python are required to use one of the following
    python eclasses: python-r1, python-single-r1, or python-any-r1. For
    documentation on choosing the correct eclass, please see the Python project
    wiki page on eclasses [#]_.

    .. [#] https://wiki.gentoo.org/wiki/Project:Python/Eclasses
    """

    def __init__(self, eclass, dep_type, dep, **kwargs):
        super().__init__(**kwargs)
        self.eclass = eclass
        self.dep_type = dep_type
        self.dep = dep

    @property
    def desc(self):
        return f'missing {self.eclass} eclass usage for {self.dep_type}="{self.dep}"'


class PythonSingleUseMismatch(results.VersionedResult, results.Warning):
    """Package has mismatched PYTHON_SINGLE_TARGET and PYTHON_TARGETS flags.

    The package declares both PYTHON_SINGLE_TARGET and PYTHON_TARGETS flags but
    each includes a different set of supported Python implementations. This
    either indicates a bug in the eclasses or the package is manually changing
    the flags.
    """

    def __init__(self, flags, single_flags, **kwargs):
        super().__init__(**kwargs)
        self.flags = tuple(flags)
        self.single_flags = tuple(single_flags)

    @property
    def desc(self):
        flags = ' '.join(self.flags)
        single_flags = ' '.join(self.single_flags)
        return (
            "mismatched flags in IUSE: "
            f"PYTHON_TARGETS=( {flags} ) but "
            f"PYTHON_SINGLE_TARGET=( {single_flags} )"
        )


class PythonMissingRequiredUse(results.VersionedResult, results.Warning):
    """Package is missing PYTHON_REQUIRED_USE.

    The python-r1 and python-single-r1 eclasses require the packages to
    explicitly specify `REQUIRED_USE=${PYTHON_REQUIRED_USE}`. If Python is used
    conditionally, it can be wrapped in appropriate USE conditionals.
    """

    @property
    def desc(self):
        return 'missing REQUIRED_USE="${PYTHON_REQUIRED_USE}"'


class PythonMissingDeps(results.VersionedResult, results.Warning):
    """Package is missing PYTHON_DEPS.

    The python-r1 and python-single-r1 eclasses require the packages
    to explicitly reference `${PYTHON_DEPS}` in RDEPEND (and DEPEND,
    if necessary); python-any-r1 requires it in DEPEND.

    If Python is used conditionally, the dependency can be wrapped
    in appropriate USE conditionals.
    """

    def __init__(self, dep_type, **kwargs):
        super().__init__(**kwargs)
        self.dep_type = dep_type

    @property
    def desc(self):
        return f'missing {self.dep_type}="${{PYTHON_DEPS}}"'


class PythonRuntimeDepInAnyR1(results.VersionedResult, results.Warning):
    """Package depends on Python at runtime but uses any-r1 eclass.

    The python-any-r1 eclass is meant to be used purely for build-time
    dependencies on Python. However, this package lists Python as a runtime
    dependency. If this is intentional, the package needs to switch to
    python-r1 or python-single-r1 eclass, otherwise the runtime dependency
    should be removed.
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


class PythonEclassError(results.VersionedResult, results.Error):
    """Generic python eclass error."""

    def __init__(self, msg, **kwargs):
        super().__init__(**kwargs)
        self.msg = msg

    @property
    def desc(self):
        return self.msg


class PythonCheck(Check):
    """Python eclass checks.

    Check whether Python eclasses are used for Python packages, and whether
    they don't suffer from common mistakes.
    """

    known_results = frozenset([
        MissingPythonEclass, PythonSingleUseMismatch, PythonMissingRequiredUse,
        PythonMissingDeps, PythonRuntimeDepInAnyR1, PythonEclassError,
    ])

    @staticmethod
    def get_python_eclass(pkg):
        eclasses = set(ECLASSES).intersection(pkg.inherited)
        # All three eclasses block one another, but check and throw an error
        # just in case it isn't caught when sourcing the ebuild.
        if len(eclasses) > 1:
            raise ValueError(
                f"python eclasses are mutually exclusive: [ {', '.join(eclasses)} ]")
        return eclasses.pop() if eclasses else None

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

    def feed(self, pkg):
        try:
            eclass = self.get_python_eclass(pkg)
        except ValueError as e:
            yield PythonEclassError(str(e), pkg=pkg)
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
                    recomm = "python-r1 or python-single-r1"
                else:
                    recomm = "python-any-r1"
                yield MissingPythonEclass(recomm, attr.upper(), str(p), pkg=pkg)
        elif eclass in ('python-r1', 'python-single-r1'):
            # grab Python implementations from IUSE
            flags = {x[len(IUSE_PREFIX):] for x in pkg.iuse if x.startswith(IUSE_PREFIX)}
            s_flags = {
                x[len(IUSE_PREFIX_S):] for x in pkg.iuse if x.startswith(IUSE_PREFIX_S)}

            # python-single-r1 should have matching PT and PST
            # (except when there is only one impl, whereas PST is not generated)
            got_single_impl = len(flags) == 1 and not s_flags
            if (eclass == 'python-single-r1' and flags != s_flags
                    and not got_single_impl):
                yield PythonSingleUseMismatch(sorted(flags), sorted(s_flags), pkg=pkg)

            if eclass == 'python-r1' or got_single_impl:
                req_use_args = (flags, IUSE_PREFIX, OrRestriction)
            else:
                req_use_args = (s_flags, IUSE_PREFIX_S, JustOneRestriction)
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
            for attr in ("depend", "bdepend"):
                for p in iflatten_instance(getattr(pkg, attr), atom):
                    if not p.blocks and p.key in INTERPRETERS:
                        break
                else:
                    continue
                break
            else:
                yield PythonMissingDeps('DEPEND', pkg=pkg)
