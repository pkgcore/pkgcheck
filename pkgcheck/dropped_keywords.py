# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: BSD/GPL2

from collections import defaultdict

from pkgcheck.base import Template, package_feed, versioned_feed, Result


class DroppedKeywordWarning(Result):
    """Arch keywords dropped during pkg version bumping"""

    __slots__ = ("arches", "category", "package", "version")
    threshold = versioned_feed

    def __init__(self, pkg, arches):
        Result.__init__(self)
        self._store_cpv(pkg)
        self.arches = arches

    @property
    def short_desc(self):
        return "keyword%s dropped: %s" % (
            's'[self.arches == 1:], ', '.join(sorted(self.arches)))


class DroppedKeywordsReport(Template):
    """scan pkgs for keyword dropping across versions"""

    feed_type = package_feed
    known_results = (DroppedKeywordWarning,)

    def __init__(self, options):
        Template.__init__(self, options)
        self.arches = frozenset(options.arches)

    def feed(self, pkgset, reporter):
        # We need to skip live ebuilds otherwise they're flagged. Currently, we
        # assume live ebuilds have versions matching *9999*.
        pkgset = [pkg for pkg in pkgset if "9999" not in pkg.version]

        if len(pkgset) <= 1:
            return

        lastpkg = pkgset[-1]
        state = set(x.lstrip("~") for x in lastpkg.keywords)
        arches = set(self.arches)
        dropped = defaultdict(list)
        # pretty simple; pull the last keywords, walk backwards
        # the difference (ignoring unstable/stable) should be empty;
        # if it is, report; meanwhile, add the new arch in, and continue
        for pkg in reversed(pkgset):
            oldstate = set(x.lstrip("~") for x in pkg.keywords)
            for key in oldstate.difference(state):
                if key.startswith("-"):
                    continue
                elif "-%s" % key in state:
                    continue
                elif key in arches:
                    dropped[lastpkg].append(key)
                    arches.discard(key)
            state = oldstate
            lastpkg = pkg

        for pkg in dropped.iterkeys():
            reporter.add_report(DroppedKeywordWarning(pkg, dropped[pkg]))
