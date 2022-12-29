from collections import defaultdict

from pkgcore.ebuild.misc import sort_keywords
from pkgcore.restrictions import packages, values
from snakeoil.strings import pluralism

from .. import addons, results, sources
from . import GentooRepoCheck


class UnstableOnly(results.PackageResult, results.Info):
    """Package/keywords that are strictly unstable."""

    def __init__(self, versions, arches, **kwargs):
        super().__init__(**kwargs)
        self.versions = tuple(versions)
        self.arches = tuple(arches)

    @property
    def desc(self):
        es = pluralism(self.arches, plural="es")
        arches = ", ".join(self.arches)
        versions = ", ".join(self.versions)
        return f"for arch{es}: [ {arches} ], all versions are unstable: [ {versions} ]"


class UnstableOnlyCheck(GentooRepoCheck):
    """Scan for packages that have just unstable keywords."""

    _source = sources.PackageRepoSource
    required_addons = (addons.StableArchesAddon,)
    known_results = frozenset([UnstableOnly])

    def __init__(self, *args, stable_arches_addon=None):
        super().__init__(*args)
        arches = {x.strip().lstrip("~") for x in self.options.stable_arches}

        # stable, then unstable, then file
        self.arch_restricts = {}
        for arch in arches:
            self.arch_restricts[arch] = [
                packages.PackageRestriction("keywords", values.ContainmentMatch2((arch,))),
                packages.PackageRestriction("keywords", values.ContainmentMatch2((f"~{arch}",))),
            ]

    def feed(self, pkgset):
        # stable, then unstable, then file
        unstable_arches = defaultdict(list)
        for k, v in self.arch_restricts.items():
            stable = unstable = None
            for x in pkgset:
                if v[0].match(x):
                    stable = x
                    break
            if stable is not None:
                continue
            if unstable := tuple(x for x in pkgset if v[1].match(x)):
                unstable_arches[unstable].append(k)

        # collapse reports by available versions
        for pkgs in unstable_arches.keys():
            versions = (x.fullver for x in sorted(pkgs))
            yield UnstableOnly(versions, sort_keywords(unstable_arches[pkgs]), pkg=pkgs[0])
