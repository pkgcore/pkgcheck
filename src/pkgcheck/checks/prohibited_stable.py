import typing

from pkgcore.ebuild.misc import sort_keywords
from snakeoil.strings import pluralism

from .. import results
from . import OptionalCheck


class ProhibitedStableKeywords(results.VersionResult, results.Error):
    """Package uses stable keywords prohibited by the repository."""

    def __init__(self, arches, **kwargs):
        super().__init__(**kwargs)
        self.arches = tuple(sort_keywords(arches))

    @property
    def desc(self):
        s = pluralism(self.arches)
        arches = ", ".join(self.arches)
        return f"prohibited stable keyword{s}: [ {arches} ]"


class ProhibitedStableKeywordsCheck(OptionalCheck):
    """Scan for packages using stable keywords prohibited by the repository."""

    known_results: typing.ClassVar[frozenset] = frozenset({ProhibitedStableKeywords})

    # acct-group and acct-user eclasses define KEYWORDS
    # See https://bugs.gentoo.org/342185
    ignored_categories: typing.ClassVar[frozenset] = frozenset({"acct-group", "acct-user"})

    def feed(self, pkg):
        if pkg.category in self.ignored_categories:
            return

        arches = {k for k in pkg.keywords if not k.startswith(("~", "-"))}
        if not arches:
            return

        yield ProhibitedStableKeywords(arches, pkg=pkg)
