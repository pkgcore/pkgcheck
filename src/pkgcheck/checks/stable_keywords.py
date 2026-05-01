from collections import defaultdict

from pkgcore.ebuild.misc import sort_keywords
from pkgcore.restrictions import packages, values
from snakeoil.strings import pluralism

from .. import addons, results, sources
from . import OptionalCheck


class DisallowedStableKeywords(results.VersionResult, results.Error):
    """Package uses stable keywords, which are disallowed in this repository."""

    def __init__(self, arches, **kwargs):
        super().__init__(**kwargs)
        self.arches = tuple(sort_keywords(arches))

    @property
    def desc(self):
        s = pluralism(self.arches)
        arches = ", ".join(self.arches)
        return f"disallowed stable keyword{s}: [ {arches} ]"


class DisallowedStableKeywordsCheck(OptionalCheck):
    """Scan for packages using stable keywords in repositories where they are not allowed."""

    required_addons = (addons.StableArchesAddon,)
    known_results = frozenset({DisallowedStableKeywords})

    # acct-group and acct-user eclasses define KEYWORDS
    # See https://bugs.gentoo.org/342185
    ignored_categories = frozenset({"acct-group", "acct-user"})

    def __init__(self, *args, stable_arches_addon=None):
        super().__init__(*args)
        self.arches = frozenset({x.strip().lstrip("~") for x in self.options.stable_arches})

        self.arch_restricts = {
            arch: packages.PackageRestriction("keywords", values.ContainmentMatch2((arch,)))
            for arch in self.arches
        }

    def feed(self, pkg):
        if pkg.category in self.ignored_categories:
            return

        arches = frozenset({arch for arch, r in self.arch_restricts.items() if r.match(pkg)})
        if not arches:
            return

        yield DisallowedStableKeywords(arches, pkg=pkg)
