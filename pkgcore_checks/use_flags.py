# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: GPL2

from pkgcore_checks.base import template, profile_options, package_feed, Result
from pkgcore_checks.util import get_use_local_desc
from pkgcore.util.lists import iflatten_instance
from pkgcore.util.demandload import demandload
demandload(globals(), "pkgcore.util.xml:escape ")

class UnusedLocalFlagCheck(template):

    """
    check for unused use.local.desc entries
    """

    feed_type = package_feed
    requires = profile_options

    def __init__(self, options):
        template.__init__(self, options)
        self.flags = {}

    # we're a profile based option, thus we get extra crap we don't need
    def start(self, repo, *a):
        self.flags = get_use_local_desc(self.options.profile_base_dir)
    
    def feed(self, pkgs, reporter):
        for restrict, flags in self.flags.get(pkgs[0].key, {}).iteritems():
            unused = flags.difference(iflatten_instance(
                pkg.iuse for pkg in pkgs if restrict.match(pkg)))
            if unused:
                reporter.add_report(UnusedLocalFlags(restrict, unused))


class UnusedLocalFlags(Result):
    
    """
    unused use.local.desc flag(s)
    """
    
    __slots__ = ("category", "package", "atom", "flags")

    def __init__(self, restrict, flags):
        Result.__init__(self)
        # tricky, but it works; atoms have the same attrs
        self._store_cp(restrict)
        self.atom = str(restrict)
        self.flags = tuple(sorted(flags))
    
    def to_str(self):
        if self.atom == "%s/%s" % (self.category, self.package):
            s = ''
        else:
            s = "atom(%s), " % self.atom
        return "%s/%s: use.local.desc%s unused flag(s): %s" % \
            (self.category, self.package, s,
		', '.join(self.flags))

    def to_xml(self):
        return \
"""<check name="%s">
    <category>%s</category>
    <package>%s</package>
    <msg>%s</msg>
</check>""" % (self.__class__.__name__, self.category, self.package,
    escape("atom %s unused use.local.desc flags: %s" % 
	(self.atom, ', '.join(self.flags))))
