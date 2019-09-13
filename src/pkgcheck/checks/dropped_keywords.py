from collections import defaultdict

from .. import addons, base


class DroppedKeywords(base.VersionedResult, base.Warning):
    """Arch keywords dropped during version bumping."""

    def __init__(self, arches, **kwargs):
        super().__init__(**kwargs)
        self.arches = tuple(arches)

    @property
    def desc(self):
        return ', '.join(self.arches)


class DroppedKeywordsCheck(base.Check):
    """Scan packages for keyword dropping across versions."""

    feed_type = base.package_feed
    scope = base.package_scope
    required_addons = (addons.ArchesAddon,)
    known_results = (DroppedKeywords,)

    def __init__(self, options, arches):
        super().__init__(options)
        self.arches = frozenset(options.arches)

    def feed(self, pkgset):
        # skip live ebuilds otherwise they're flagged
        pkgset = [pkg for pkg in pkgset if not pkg.live]

        if len(pkgset) <= 1:
            return

        seen_arches = set()
        previous_arches = set()
        changes = defaultdict(list)
        for pkg in pkgset:
            pkg_arches = set(x.lstrip("~-") for x in pkg.keywords)
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
                disabled_arches = set(x.lstrip("-") for x in pkg.keywords if x.startswith('-'))
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
