# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: GPL2


from pkgcore_checks.base import Template, package_feed, versioned_feed, Result


class DroppedKeywordWarning(Result):
    """Arch keywords dropped during pkg version bumping"""

    __slots__ = ("arch", "category", "package", "version")
    threshold = versioned_feed

    def __init__(self, arch, pkg):
        Result.__init__(self)
        self._store_cpv(pkg)
        self.arch = arch

    @property
    def short_desc(self):
        return "keyword %s dropped" % self.arch

    def to_str(self):
        return "%s/%s-%s: dropped keyword %s" % (self.category, self.package,
            self.version, self.arch)


class DroppedKeywordsReport(Template):
    """scan pkgs for keyword dropping across versions"""

    feed_type = package_feed
    known_results = (DroppedKeywordWarning,)

    def __init__(self, options):
        Template.__init__(self, options)
        self.arches = dict((k, None) for k in options.arches)

    def feed(self, pkgset, reporter):
        if len(pkgset) == 1:
            return

        lastpkg = pkgset[-1]
        state = set(x.lstrip("~") for x in lastpkg.keywords)
        arches = set(self.arches)
        dropped = []
        # pretty simple; pull the last keywords, walk backwards
        # the difference (ignoring unstable/stable) should be empty;
        # if it is, report; meanwhile, add the new arch in, and continue
        for pkg in reversed(pkgset[:-1]):
            oldstate = set(x.lstrip("~") for x in pkg.keywords)
            for key in oldstate.difference(state):
                if key.startswith("-"):
                    continue
                elif "-%s" % key in state:
                    continue
                elif key in arches:
                    dropped.append((key, lastpkg))
                    arches.discard(key)
            state = oldstate
            lastpkg = pkg
 
        for key, pkg in dropped:
            reporter.add_report(DroppedKeywordWarning(key, pkg))
