from pkgcore.ebuild.atom import atom

from snakeoil.sequences import iflatten_instance

from .. import base, addons


# NB: distutils-r1 inherits one of the first two
ECLASSES = ('python-r1', 'python-single-r1', 'python-any-r1')

# NB: dev-java/jython omitted as not supported by the eclasses atm
INTERPRETERS = (
    'dev-lang/python',
    'dev-python/pypy',
    'dev-python/pypy3',
    'dev-python/pypy-bin',
    'dev-python/pypy3-bin',
    'virtual/pypy',
    'virtual/pypy3',
)

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


class PythonReport(base.Template):
    """Python eclass issue scans.

    Check whether Python eclasses are used for Python packages, and whether
    they don't suffer from common mistakes.
    """

    feed_type = base.versioned_feed
    known_results = (MissingPythonEclass, PythonSingleUseMismatch)

    @staticmethod
    def get_python_eclass(pkg):
        eclasses = set(pkg.inherited).intersection(ECLASSES)
        # all three eclasses block one another
        assert(len(eclasses) <= 1)
        return eclasses.pop() if eclasses else None

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
            if (eclass == 'python-single-r1' and flags != s_flags
                    and (len(flags) > 1 or len(s_flags) > 0)):
                yield PythonSingleUseMismatch(pkg, flags, s_flags)
