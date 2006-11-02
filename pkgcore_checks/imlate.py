# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: GPL2

from pkgcore.restrictions import packages, values
from pkgcore.util.currying import pre_curry
from pkgcore_checks import base, addons


class SourceArchesAddon(addons.Addon):

    @staticmethod
    def mangle_option_parser(parser):
        parser.add_option(
            "--source-arches", action='callback', dest='reference_arches',
            default=addons.ArchesAddon.default_arches,
            type='string', callback=addons.ArchesAddon._record_arches,
            help="comma seperated list of what arches to compare against for "
            "imlate, defaults to %s" % (
                ",".join(addons.ArchesAddon.default_arches),))


class ImlateReport(base.template):

    """
    scan for ebuilds that can be stabled based upon stabling status for 
    other arches
    """

    feed_type = base.package_feed
    required_addons = (addons.ArchesAddon, SourceArchesAddon)

    def __init__(self, options):
        base.template.__init__(self, options)
        arches = frozenset(x.strip().lstrip("~") for x in options.arches)
        self.target_arches = frozenset("~%s" % x.strip().lstrip("~") 
            for x in arches)
        self.source_arches = frozenset(x.lstrip("~") 
            for x in options.reference_arches)
        self.source_filter = packages.PackageRestriction("keywords",
            values.ContainmentMatch(*self.source_arches))

    def feed(self, pkgset, reporter):
        #candidates.
        fmatch = self.source_filter.match
        remaining = set(self.target_arches)
        for pkg in reversed(pkgset):
            if not fmatch(pkg):
                continue
            unstable_keys = remaining.intersection(pkg.keywords)
            if unstable_keys:
                reporter.add_report(LaggingStableInfo(pkg,
                    sorted(unstable_keys)))
                remaining.discard(unstable_keys)
                if not remaining:
                    break


class LaggingStableInfo(base.Result):

    """Arch that is behind another from a stabling standpoint"""
    
    __slots__ = ("category", "package", "version", "keywords",
        "existing_keywords")
    
    def __init__(self, pkg, keywords):
        base.Result.__init__(self)
        self.category = pkg.category
        self.package = pkg.package
        self.version = pkg.fullver
        self.keywords = keywords
        self.stable = tuple(str(x) for x in pkg.keywords
            if not x[0] in ("~", "-"))
    
    def to_str(self):
        return "%s/%s-%s: stabled [ %s ], potentials: [ %s ]" % \
            (self.category, self.package, self.version, 
            ", ".join(self.stable), ", ".join(self.keywords))

    def to_xml(self):
        return \
"""<check name="%s">
    <category>%s</category>
    <package>%s</package>
    <version>%s</version>
    <keyword>%s</keyword>
    <msg>%s</msg>
</check>""" % (self.__class__.__name__, self.category, self.package,
    self.version, "</keyword>\n\t<keyword>".join(self.keywords), 
    "potential for stabling, prexisting stable- %s" % ", ".join(self.stable))
