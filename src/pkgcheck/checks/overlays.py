from snakeoil.sequences import iflatten_instance
from snakeoil.strings import pluralism as _pl

from .. import base, results, sources
from . import ExplicitlyEnabledCheck, OverlayRepoCheck, repo_metadata


class UnusedInMastersLicenses(results.VersionedResult, results.Warning):
    """Licenses detected that are unused in the master repo(s).

    In other words, they're likely to be removed so should be copied to the overlay.
    """

    def __init__(self, licenses, **kwargs):
        super().__init__(**kwargs)
        self.licenses = tuple(licenses)

    @property
    def desc(self):
        return "unused license%s in master repo(s): %s" % (
            _pl(self.licenses), ', '.join(self.licenses))


class UnusedInMastersMirrors(results.VersionedResult, results.Warning):
    """Mirrors detected that are unused in the master repo(s).

    In other words, they're likely to be removed so should be copied to the overlay.
    """

    def __init__(self, mirrors, **kwargs):
        super().__init__(**kwargs)
        self.mirrors = tuple(mirrors)

    @property
    def desc(self):
        return "unused mirror%s in master repo(s): %s" % (
            _pl(self.mirrors), ', '.join(self.mirrors))


class UnusedInMastersEclasses(results.VersionedResult, results.Warning):
    """Eclasses detected that are unused in the master repo(s).

    In other words, they're likely to be removed so should be copied to the overlay.
    """

    def __init__(self, eclasses, **kwargs):
        super().__init__(**kwargs)
        self.eclasses = tuple(eclasses)

    @property
    def desc(self):
        return "unused eclass%s in master repo(s): %s" % (
            _pl(self.eclasses, plural='es'), ', '.join(self.eclasses))


class UnusedInMastersGlobalUse(results.VersionedResult, results.Warning):
    """Global USE flags detected that are unused in the master repo(s).

    In other words, they're likely to be removed so should be copied to the overlay.
    """

    def __init__(self, flags, **kwargs):
        super().__init__(**kwargs)
        self.flags = tuple(flags)

    @property
    def desc(self):
        return "use.desc unused flag%s in master repo(s): %s" % (
            _pl(self.flags), ', '.join(self.flags))


class UnusedInMastersCheck(repo_metadata._MirrorsCheck,
                           OverlayRepoCheck, ExplicitlyEnabledCheck):
    """Check for various metadata that may be removed from master repos."""

    scope = base.repository_scope
    _source = sources.RepositoryRepoSource
    known_results = frozenset([
        UnusedInMastersLicenses, UnusedInMastersMirrors, UnusedInMastersEclasses,
        UnusedInMastersGlobalUse,
    ])

    def start(self):
        self.unused_master_licenses = set()
        self.unused_master_mirrors = set()
        self.unused_master_eclasses = set()
        self.unused_master_flags = set()

        # combine licenses/mirrors/eclasses/flags from all master repos
        for repo in self.options.target_repo.masters:
            self.unused_master_licenses.update(repo.licenses)
            self.unused_master_mirrors.update(repo.mirrors.keys())
            self.unused_master_eclasses.update(repo.eclass_cache.eclasses.keys())
            self.unused_master_flags.update(
                flag for matcher, (flag, desc) in repo.config.use_desc)

        # determine unused licenses/mirrors/eclasses/flags across all master repos
        for repo in self.options.target_repo.masters:
            for pkg in repo:
                self.unused_master_licenses.difference_update(iflatten_instance(pkg.license))
                self.unused_master_mirrors.difference_update(self._get_mirrors(pkg))
                self.unused_master_eclasses.difference_update(pkg.inherited)
                self.unused_master_flags.difference_update(
                    pkg.iuse_stripped.difference(pkg.local_use.keys()))

    def feed(self, pkg):
        # report licenses used in the pkg but not in any pkg from the master repo(s)
        if self.unused_master_licenses:
            pkg_licenses = set(iflatten_instance(pkg.license))
            licenses = self.unused_master_licenses & pkg_licenses
            if licenses:
                yield UnusedInMastersLicenses(sorted(licenses), pkg=pkg)

        # report mirrors used in the pkg but not in any pkg from the master repo(s)
        if self.unused_master_mirrors:
            pkg_mirrors = self._get_mirrors(pkg)
            mirrors = self.unused_master_mirrors & pkg_mirrors
            if mirrors:
                yield UnusedInMastersMirrors(sorted(mirrors), pkg=pkg)

        # report eclasses used in the pkg but not in any pkg from the master repo(s)
        if self.unused_master_eclasses:
            pkg_eclasses = set(pkg.inherited)
            eclasses = self.unused_master_eclasses & pkg_eclasses
            if eclasses:
                yield UnusedInMastersEclasses(sorted(eclasses), pkg=pkg)

        # report global USE flags used in the pkg but not in any pkg from the master repo(s)
        if self.unused_master_flags:
            non_local_use = pkg.iuse_stripped.difference(pkg.local_use.keys())
            flags = self.unused_master_flags.intersection(non_local_use)
            if flags:
                yield UnusedInMastersGlobalUse(sorted(flags), pkg=pkg)
