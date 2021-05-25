import itertools

from pkgcore.ebuild.atom import atom
from pkgcore.restrictions import packages, values
from pkgcore.restrictions.boolean import JustOneRestriction, OrRestriction
from snakeoil.sequences import iflatten_instance
from snakeoil.strings import pluralism

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


class PythonMissingRequiredUse(results.VersionResult, results.Warning):
    """Package is missing PYTHON_REQUIRED_USE.

    The python-r1 and python-single-r1 eclasses require the packages to
    explicitly specify `REQUIRED_USE=${PYTHON_REQUIRED_USE}`. If Python is used
    conditionally, it can be wrapped in appropriate USE conditionals.
    """

    @property
    def desc(self):
        return 'missing REQUIRED_USE="${PYTHON_REQUIRED_USE}"'


class PythonMissingDeps(results.VersionResult, results.Warning):
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


class PythonRuntimeDepInAnyR1(results.VersionResult, results.Warning):
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


class PythonEclassError(results.VersionResult, results.Error):
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
        MissingPythonEclass, PythonMissingRequiredUse,
        PythonMissingDeps, PythonRuntimeDepInAnyR1, PythonEclassError,
    ])

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
            eclass = get_python_eclass(pkg)
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
            iuse = [x.lstrip('+-') for x in pkg.iuse]
            flags = {x[len(IUSE_PREFIX):] for x in iuse if x.startswith(IUSE_PREFIX)}
            s_flags = {
                x[len(IUSE_PREFIX_S):] for x in iuse if x.startswith(IUSE_PREFIX_S)}

            if eclass == 'python-r1':
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


class PythonCompatUpdate(results.VersionResult, results.Info):
    """PYTHON_COMPAT can be updated to support newer python version(s)."""

    def __init__(self, updates, **kwargs):
        super().__init__(**kwargs)
        self.updates = tuple(updates)

    @property
    def desc(self):
        s = pluralism(self.updates)
        updates = ', '.join(self.updates)
        return f'PYTHON_COMPAT update{s} available: {updates}'


class PythonCompatCheck(Check):
    """Check python ebuilds for possible PYTHON_COMPAT updates.

    Supports ebuilds inheriting python-r1, python-single-r1, and python-any-r1.
    """

    known_results = frozenset([PythonCompatUpdate])

    def __init__(self, *args):
        super().__init__(*args)
        repo = self.options.target_repo
        # sorter for python targets leveraging USE_EXPAND flag ordering from repo
        self.sorter = repo.use_expand_sorter('python_targets')

        # determine available PYTHON_TARGET use flags
        targets = []
        for target, _desc in repo.config.use_expand_desc.get(IUSE_PREFIX[:-1], ()):
            if target[len(IUSE_PREFIX):].startswith('python'):
                targets.append(target[len(IUSE_PREFIX):])
        multi_targets = tuple(sorted(targets, key=self.sorter))

        # determine available PYTHON_SINGLE_TARGET use flags
        targets = []
        for target, _desc in repo.config.use_expand_desc.get(IUSE_PREFIX_S[:-1], ()):
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
