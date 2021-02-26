from snakeoil.sequences import iflatten_instance
from snakeoil.strings import pluralism

from .. import results, sources
from . import MirrorsCheck, OptionalCheck, OverlayRepoCheck, RepoCheck


class UnusedInMastersLicenses(results.VersionResult, results.Warning):
    """Licenses detected that are unused in the master repo(s).

    In other words, they're likely to be removed so should be copied to the overlay.
    """

    def __init__(self, licenses, **kwargs):
        super().__init__(**kwargs)
        self.licenses = tuple(licenses)

    @property
    def desc(self):
        s = pluralism(self.licenses)
        licenses = ', '.join(self.licenses)
        return f'unused license{s} in master repo(s): {licenses}'


class UnusedInMastersMirrors(results.VersionResult, results.Warning):
    """Mirrors detected that are unused in the master repo(s).

    In other words, they're likely to be removed so should be copied to the overlay.
    """

    def __init__(self, mirrors, **kwargs):
        super().__init__(**kwargs)
        self.mirrors = tuple(mirrors)

    @property
    def desc(self):
        s = pluralism(self.mirrors)
        mirrors = ', '.join(self.mirrors)
        return f'unused mirror{s} in master repo(s): {mirrors}'


class UnusedInMastersEclasses(results.VersionResult, results.Warning):
    """Eclasses detected that are unused in the master repo(s).

    In other words, they're likely to be removed so should be copied to the overlay.
    """

    def __init__(self, eclasses, **kwargs):
        super().__init__(**kwargs)
        self.eclasses = tuple(eclasses)

    @property
    def desc(self):
        es = pluralism(self.eclasses, plural='es')
        eclasses = ', '.join(self.eclasses)
        return f'unused eclass{es} in master repo(s): {eclasses}'


class UnusedInMastersGlobalUse(results.VersionResult, results.Warning):
    """Global USE flags detected that are unused in the master repo(s).

    In other words, they're likely to be removed so should be copied to the overlay.
    """

    def __init__(self, flags, **kwargs):
        super().__init__(**kwargs)
        self.flags = tuple(flags)

    @property
    def desc(self):
        s = pluralism(self.flags)
        flags = ', '.join(self.flags)
        return f'use.desc unused flag{s} in master repo(s): {flags}'


class UnusedInMastersCheck(MirrorsCheck, OverlayRepoCheck, RepoCheck, OptionalCheck):
    """Check for various metadata that may be removed from master repos."""

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
                self.unused_master_mirrors.difference_update(self.get_mirrors(pkg))
                self.unused_master_eclasses.difference_update(pkg.inherited)
                self.unused_master_flags.difference_update(
                    pkg.iuse_stripped.difference(pkg.local_use.keys()))

    def feed(self, pkg):
        # report licenses used in the pkg but not in any pkg from the master repo(s)
        if self.unused_master_licenses:
            pkg_licenses = set(iflatten_instance(pkg.license))
            if licenses := self.unused_master_licenses.intersection(pkg_licenses):
                yield UnusedInMastersLicenses(sorted(licenses), pkg=pkg)

        # report mirrors used in the pkg but not in any pkg from the master repo(s)
        if self.unused_master_mirrors:
            pkg_mirrors = self.get_mirrors(pkg)
            if mirrors := self.unused_master_mirrors.intersection(pkg_mirrors):
                yield UnusedInMastersMirrors(sorted(mirrors), pkg=pkg)

        # report eclasses used in the pkg but not in any pkg from the master repo(s)
        if self.unused_master_eclasses:
            if eclasses := self.unused_master_eclasses.intersection(pkg.inherited):
                yield UnusedInMastersEclasses(sorted(eclasses), pkg=pkg)

        # report global USE flags used in the pkg but not in any pkg from the master repo(s)
        if self.unused_master_flags:
            non_local_use = pkg.iuse_stripped.difference(pkg.local_use.keys())
            if flags := self.unused_master_flags.intersection(non_local_use):
                yield UnusedInMastersGlobalUse(sorted(flags), pkg=pkg)
