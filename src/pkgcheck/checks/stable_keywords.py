from collections import defaultdict

from pkgcore.ebuild.misc import sort_keywords
from pkgcore.restrictions import packages, values
from snakeoil.strings import pluralism

from .. import addons, results, sources
from . import OptionalCheck


class StableKeywords(results.PackageResult, results.Error):
    """Package uses stable keywords."""

    def __init__(self, versions, arches, **kwargs):
        super().__init__(**kwargs)
        self.versions = tuple(versions)
        self.arches = tuple(arches)

    @property
    def desc(self):
        s = pluralism(self.arches)
        arches = ", ".join(self.arches)
        versions = ", ".join(self.versions)
        return f"stable keyword{s} [ {arches} ] used on version{s}: [ {versions} ]"


class StableKeywordsCheck(OptionalCheck):
    """Scan for packages using stable keywords."""

    _source = sources.PackageRepoSource
    required_addons = (addons.StableArchesAddon,)
    known_results = frozenset([StableKeywords])

    def __init__(self, *args, stable_arches_addon=None):
        super().__init__(*args)
        self.arches = {x.strip().lstrip("~") for x in self.options.stable_arches}

        self.arch_restricts = {
            arch: packages.PackageRestriction("keywords", values.ContainmentMatch2((arch,)))
            for arch in self.arches
        }

    def feed(self, pkgset):
        pkgs_arches = defaultdict(set)
        for arch, r in self.arch_restricts.items():
            for pkg in pkgset:
                if r.match(pkg):
                    pkgs_arches[pkg].add(arch)

        # invert
        arches_pkgs = defaultdict(list)
        for pkg, arches in pkgs_arches.items():
            arches_pkgs[frozenset(arches)].append(pkg)

        # collapse reports by sets of arches
        for arches, pkgs in arches_pkgs.items():
            versions = (pkg.fullver for pkg in sorted(pkgs))
            yield StableKeywords(versions, sort_keywords(arches), pkg=pkgs[0])
