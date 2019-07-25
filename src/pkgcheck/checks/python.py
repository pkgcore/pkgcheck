from pkgcore.ebuild.atom import atom
from pkgcore.restrictions.boolean import OrRestriction, JustOneRestriction
from pkgcore.restrictions import packages, values

from snakeoil.sequences import iflatten_instance

from .. import base, addons


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

IUSE_PREFIX = 'python_targets_'
IUSE_PREFIX_S = 'python_single_target_'


class MissingPythonEclass(base.Warning):
    """Package depends on Python but does not use the eclasses."""

    __slots__ = ("category", "package", "version", "eclass", "dep_type", "dep")

    threshold = base.versioned_feed

    def __init__(self, pkg, eclass, dep_type, dep):
        super().__init__()
        self._store_cpv(pkg)
        self.eclass = eclass
        self.dep_type = dep_type
        self.dep = dep

    @property
    def short_desc(self):
        return (f"Python package not using proper eclass, should use "
                f"{self.eclass} instead of {self.dep_type} on {self.dep}")


class PythonSingleUseMismatch(base.Warning):
    """Package has mismatched PYTHON_SINGLE & PYTHON_TARGETS flags."""

    __slots__ = ("category", "package", "version", "flags", "single_flags")

    threshold = base.versioned_feed

    def __init__(self, pkg, flags, single_flags):
        super().__init__()
        self._store_cpv(pkg)
        self.flags = tuple(sorted(flags))
        self.single_flags = tuple(sorted(single_flags))

    @property
    def short_desc(self):
        return (f"Python package has mismatched Python flags in IUSE: "
                f"PYTHON_TARGETS={self.flags} but "
                f"PYTHON_SINGLE_TARGET={self.single_flags}")


class PythonMissingRequiredUSE(base.Warning):
    """Package is missing PYTHON_REQUIRED_USE."""

    __slots__ = ("category", "package", "version")

    threshold = base.versioned_feed

    def __init__(self, pkg):
        super().__init__()
        self._store_cpv(pkg)

    @property
    def short_desc(self):
        return ("Python package is missing ${PYTHON_REQUIRED_USE} "
                "in REQUIRED_USE")


class PythonMissingDeps(base.Warning):
    """Package is missing PYTHON_DEPS."""

    __slots__ = ("category", "package", "version", "dep_type")

    threshold = base.versioned_feed

    def __init__(self, pkg, dep_type):
        super().__init__()
        self._store_cpv(pkg)
        self.dep_type = dep_type

    @property
    def short_desc(self):
        return ("Python package is missing ${PYTHON_DEPS} "
                f"in {self.dep_type}")


class PythonRuntimeDepInAnyR1(base.Warning):
    """Package depends on Python at runtime but uses any-r1 eclass."""

    __slots__ = ("category", "package", "version", "dep_type", "dep")

    threshold = base.versioned_feed

    def __init__(self, pkg, dep_type, dep):
        super().__init__()
        self._store_cpv(pkg)
        self.dep_type = dep_type
        self.dep = dep

    @property
    def short_desc(self):
        return (f"Package inherits python-any-r1 but has {self.dep_type} "
                f"on {self.dep}; python-r1 or python-single-r1 should "
                f"be used instead")


class PythonReport(base.Template):
    """Python eclass issue scans.

    Check whether Python eclasses are used for Python packages, and whether
    they don't suffer from common mistakes.
    """

    feed_type = base.versioned_feed
    known_results = (MissingPythonEclass, PythonSingleUseMismatch,
                     PythonMissingRequiredUSE, PythonMissingDeps,
                     PythonRuntimeDepInAnyR1)

    @staticmethod
    def get_python_eclass(pkg):
        eclasses = set(ECLASSES).intersection(pkg.inherited)
        # all three eclasses block one another
        assert(len(eclasses) <= 1)
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
                if not any(y.key in INTERPRETERS for y in x
                                                 if isinstance(y, atom)):
                    continue
                matched.add(flag[len(prefix):])
            if matched == flags:
                return True
        return False

    def feed(self, pkg):
        eclass = self.get_python_eclass(pkg)

        if eclass is None:
            # check whether we should be using one
            highest_found = None
            for attr in ("bdepend", "depend", "rdepend", "pdepend"):
                for p in iflatten_instance(getattr(pkg, attr), atom):
                    if p.key in INTERPRETERS:
                        highest_found = (attr, p)
                        # break scanning packages, go to next attr
                        break

            if highest_found is not None:
                if highest_found[0] in ("rdepend", "pdepend"):
                    recomm = "python-r1 or python-single-r1"
                else:
                    recomm = "python-any-r1"
                yield MissingPythonEclass(pkg, recomm, *highest_found)
        elif eclass in ('python-r1', 'python-single-r1'):
            # grab Python implementations from IUSE
            flags = set([x[len(IUSE_PREFIX):] for x in pkg.iuse
                                              if x.startswith(IUSE_PREFIX)])
            s_flags = set([x[len(IUSE_PREFIX_S):] for x in pkg.iuse
                                                  if x.startswith(IUSE_PREFIX_S)])

            # python-single-r1 should have matching PT and PST
            # (except when there is only one impl, whereas PST is not generated)
            got_single_impl = len(flags) == 1 and len(s_flags) == 0
            if (eclass == 'python-single-r1' and flags != s_flags
                    and not got_single_impl):
                yield PythonSingleUseMismatch(pkg, flags, s_flags)

            if eclass == 'python-r1' or got_single_impl:
                req_use_args = (flags, IUSE_PREFIX, OrRestriction)
            else:
                req_use_args = (s_flags, IUSE_PREFIX_S, JustOneRestriction)
            if not self.check_required_use(pkg.required_use, *req_use_args):
                yield PythonMissingRequiredUSE(pkg)
            if not self.check_depend(pkg.rdepend, *(req_use_args[:2])):
                yield PythonMissingDeps(pkg, 'RDEPEND')
        else:  # python-any-r1
            for attr in ("rdepend", "pdepend"):
                for p in iflatten_instance(getattr(pkg, attr), atom):
                    if p.key in INTERPRETERS:
                        yield PythonRuntimeDepInAnyR1(pkg, attr, p)
                        break
            for attr in ("depend", "bdepend"):
                for p in iflatten_instance(getattr(pkg, attr), atom):
                    if p.key in INTERPRETERS:
                        break
                else:
                    continue
                break
            else:
                yield PythonMissingDeps(pkg, 'DEPEND')
