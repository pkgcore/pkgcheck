from collections import defaultdict

from .. import addons, base, results, sources
from . import Check


class DroppedKeywords(results.VersionedResult, results.Warning):
    """Arch keywords dropped during version bumping."""

    def __init__(self, arches, **kwargs):
        super().__init__(**kwargs)
        self.arches = tuple(arches)

    @property
    def desc(self):
        return ', '.join(self.arches)


class DroppedKeywordsCheck(Check):
    """Scan packages for keyword dropping across versions."""

    scope = base.package_scope
    _source = sources.PackageRepoSource
    required_addons = (addons.ArchesAddon,)
    known_results = frozenset([DroppedKeywords])

    def __init__(self, *args, arches_addon):
        super().__init__(*args)
        self.arches = frozenset(self.options.arches)

    def feed(self, pkgset):
        # skip live ebuilds otherwise they're flagged
        pkgset = [pkg for pkg in pkgset if not pkg.live]

        if len(pkgset) <= 1:
            return

        seen_arches = set()
        previous_arches = set()
        changes = defaultdict(list)
        for pkg in pkgset:
            pkg_arches = {x.lstrip("~-") for x in pkg.keywords}
            # special keywords -*, *, and ~* override all dropped keywords
            if '*' in pkg_arches:
                drops = set()
            else:
                drops = previous_arches.difference(pkg_arches) | seen_arches.difference(pkg_arches)
            for key in drops:
                if key in self.arches:
                    changes[key].append(pkg)
            if changes:
                # ignore missing arches on previous versions that were re-enabled
                disabled_arches = {x.lstrip("-") for x in pkg.keywords if x.startswith('-')}
                adds = pkg_arches.difference(previous_arches) - disabled_arches
                for key in adds:
                    if key in changes:
                        del changes[key]
            seen_arches.update(pkg_arches)
            previous_arches = pkg_arches

        dropped = defaultdict(list)
        for key, pkgs in changes.items():
            if self.options.verbosity > 0:
                # output all pkgs with dropped keywords in verbose mode
                for pkg in pkgs:
                    dropped[pkg].append(key)
            else:
                # only report the most recent pkg with dropped keywords
                dropped[pkgs[-1]].append(key)

        for pkg, keys in dropped.items():
            yield DroppedKeywords(sorted(keys), pkg=pkg)
