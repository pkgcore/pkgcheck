from collections import defaultdict

from pkgcore.restrictions import packages, values
from snakeoil.strings import pluralism

from .. import addons, results, sources
from . import Check


class PotentialStable(results.VersionResult, results.Info):
    """Stable arches with potential stable package candidates."""

    def __init__(self, slot, stable, keywords, **kwargs):
        super().__init__(**kwargs)
        self.slot = slot
        self.stable = tuple(stable)
        self.keywords = tuple(keywords)

    @property
    def desc(self):
        es = pluralism(self.stable, plural='es')
        stable = ', '.join(self.stable)
        s = pluralism(self.keywords)
        keywords = ', '.join(self.keywords)
        return f'slot({self.slot}), stabled arch{es}: [ {stable} ], potential{s}: [ {keywords} ]'


class LaggingStable(results.VersionResult, results.Info):
    """Stable arches for stabilized package that are lagging from a stabling standpoint."""

    def __init__(self, slot, stable, keywords, **kwargs):
        super().__init__(**kwargs)
        self.slot = slot
        self.stable = tuple(stable)
        self.keywords = tuple(keywords)

    @property
    def desc(self):
        es = pluralism(self.stable, plural='es')
        stable = ', '.join(self.stable)
        keywords = ', '.join(self.keywords)
        return f'slot({self.slot}), stabled arch{es}: [ {stable} ], lagging: [ {keywords} ]'


class ImlateCheck(Check):
    """Scan for ebuilds that are lagging in stabilization."""

    _source = sources.PackageRepoSource
    required_addons = (addons.StableArchesAddon,)
    known_results = frozenset([PotentialStable, LaggingStable])

    @staticmethod
    def mangle_argparser(parser):
        parser.plugin.add_argument(
            "--source-arches", action='csv', metavar='ARCH',
            help="comma separated list of arches to compare against for lagging stabilization",
            docs="""
                Comma separated list of arches to compare against for
                lagging stabilization.

                The default arches are all stable arches (unless --arches is specified).
            """)

    def __init__(self, *args, stable_arches_addon=None):
        super().__init__(*args)
        self.all_arches = frozenset(self.options.arches)
        self.stable_arches = frozenset(arch.strip().lstrip("~") for arch in self.options.stable_arches)
        self.target_arches = frozenset(f'~{arch}' for arch in self.stable_arches)

        source_arches = self.options.source_arches
        if source_arches is None:
            source_arches = self.options.stable_arches
        self.source_arches = frozenset(
            arch.lstrip("~") for arch in source_arches)
        self.source_filter = packages.PackageRestriction(
            "keywords", values.ContainmentMatch2(self.source_arches))

    def feed(self, pkgset):
        pkg_slotted = defaultdict(list)
        for pkg in pkgset:
            pkg_slotted[pkg.slot].append(pkg)

        fmatch = self.source_filter.match
        for slot, pkgs in sorted(pkg_slotted.items()):
            slot_keywords = set().union(*(pkg.keywords for pkg in pkgs))
            stable_slot_keywords = self.all_arches.intersection(slot_keywords)
            potential_slot_stables = {'~' + x for x in stable_slot_keywords}
            newer_slot_stables = set()
            for pkg in reversed(pkgs):
                # only consider pkgs with keywords that contain the targeted arches
                if not fmatch(pkg):
                    newer_slot_stables.update(self.all_arches.intersection(pkg.keywords))
                    continue

                # current pkg stable keywords
                stable = {'~' + x for x in self.source_arches.intersection(pkg.keywords)}

                lagging = potential_slot_stables.intersection(pkg.keywords)
                # skip keywords that have newer stable versions
                lagging -= {'~' + x for x in newer_slot_stables}
                lagging -= stable
                if lagging:
                    stable_kwds = (x for x in pkg.keywords if not x[0] in ('~', '-'))
                    yield LaggingStable(
                        slot, sorted(stable_kwds), sorted(lagging), pkg=pkg)

                unstable_keywords = {x for x in pkg.keywords if x[0] == '~'}
                potential = self.target_arches.intersection(unstable_keywords)
                potential -= lagging | stable
                if potential:
                    stable_kwds = (x for x in pkg.keywords if not x[0] in ('~', '-'))
                    yield PotentialStable(
                        slot, sorted(stable_kwds), sorted(potential), pkg=pkg)

                break
