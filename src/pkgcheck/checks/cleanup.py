from snakeoil.strings import pluralism

from .. import results, sources
from . import Check


class RedundantVersion(results.VersionResult, results.Info):
    """Redundant version(s) of a package in a specific slot."""

    def __init__(self, slot, later_versions, **kwargs):
        super().__init__(**kwargs)
        self.slot = slot
        self.later_versions = tuple(later_versions)

    @property
    def desc(self):
        s = pluralism(self.later_versions)
        versions = ', '.join(self.later_versions)
        return f'slot({self.slot}) keywords are overshadowed by version{s}: {versions}'


class RedundantVersionCheck(Check):
    """Scan for overshadowed package versions.

    Scan for versions that are likely shadowed by later versions from a
    keywords standpoint (ignoring live packages that erroneously have
    keywords).

    Example: pkga-1 is keyworded amd64, pkga-2 is amd64.
    pkga-1 can potentially be removed.
    """

    _source = sources.PackageRepoSource
    known_results = frozenset([RedundantVersion])

    def feed(self, pkgset):
        if len(pkgset) == 1:
            return

        # algo is roughly thus; spot stable versions, hunt for subset
        # keyworded pkgs that are less then the max version;
        # repeats this for every overshadowing detected
        # finally, does version comparison down slot lines
        stack = []
        bad = []
        for pkg in reversed(pkgset):
            # reduce false positives for idiot keywords/ebuilds
            if pkg.live:
                continue
            curr_set = {x for x in pkg.keywords if not x.startswith("-")}
            if not curr_set:
                continue

            matches = [ver for ver, keys in stack if ver.slot == pkg.slot and
                       not curr_set.difference(keys)]

            # we've done our checks; now we inject unstable for any stable
            # via this, earlier versions that are unstable only get flagged
            # as "not needed" since their unstable flag is a subset of the
            # stable.

            # also, yes, have to use list comp here- we're adding as we go
            curr_set.update([f'~{x}' for x in curr_set if not x.startswith('~')])

            stack.append([pkg, curr_set])
            if matches:
                bad.append((pkg, matches))

        for pkg, matches in reversed(bad):
            later_versions = (x.fullver for x in sorted(matches))
            yield RedundantVersion(pkg.slot, later_versions, pkg=pkg)
