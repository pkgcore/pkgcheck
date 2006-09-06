# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: GPL2

from pkgcore_checks import base, util
from pkgcore.util.lists import iflatten_instance
from pkgcore.util.demandload import demandload
demandload(globals(), "pkgcore.util.xml:escape ")

class UnusedLocalFlagsCheck(base.template):

    """
    check for unused use.local.desc entries
    """

    feed_type = base.package_feed
    requires = base.profile_options

    def __init__(self, options):
        base.template.__init__(self, options)
        self.flags = {}

    # we're a profile based option, thus we get extra crap we don't need
    def start(self, repo, *a):
        base.template.start(self, repo, *a)
        self.flags = util.get_use_local_desc(self.options.profile_base_dir)
    
    def feed(self, pkgs, reporter):
        for restrict, flags in self.flags.get(pkgs[0].key, {}).iteritems():
            unused = flags.difference(iflatten_instance(
                pkg.iuse for pkg in pkgs if restrict.match(pkg)))
            if unused:
                reporter.add_report(UnusedLocalFlags(restrict, unused))


class UnusedLocalFlags(base.Result):
    
    """
    unused use.local.desc flag(s)
    """
    
    __slots__ = ("category", "package", "atom", "flags")

    def __init__(self, restrict, flags):
        base.Result.__init__(self)
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


class UnusedGlobalFlagsCheck(base.template):
    """
    check for unused use.desc entries
    """
    
    feed_type = base.versioned_feed
    enabling_threshold = base.repository_feed
    requires = base.profile_options

    def __init__(self, options):
        base.template.__init__(self, options)
        self.flags = None
    
    def start(self, repo, *a):
        base.template.start(self, repo, *a)
        self.flags = set(util.get_use_desc(self.options.profile_base_dir))

    def feed(self, pkg, reporter):
        self.flags.difference_update(pkg.iuse)
    
    def finish(self, reporter):
        if self.flags:
            reporter.add_report(UnusedGlobalFlags(self.flags))
        self.flags.clear()


class UnusedGlobalFlags(base.Result):
    
    """
    unused use.local.desc flag(s)
    """
    
    __slots__ = ("flags",)

    def __init__(self, flags):
        base.Result.__init__(self)
        # tricky, but it works; atoms have the same attrs
        self.flags = tuple(sorted(flags))
    
    def to_str(self):
        return "use.desc unused flag(s): %s" % \
    		', '.join(self.flags)

    def to_xml(self):
        return \
"""<check name="%s">
    <msg>%s</msg>
</check>""" % (self.__class__.__name__, 
    escape("use.desc unused flags: %s" % ', '.join(self.flags)))
