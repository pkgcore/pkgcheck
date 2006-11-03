# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: GPL2

from pkgcore_checks.base import Template, versioned_feed, Result

class DeprecatedEclassReport(Template):

    feed_type = versioned_feed

    blacklist = frozenset((
    '64-bit',
    'darcs',
    'db4-fix',
    'debian',
    'embassy-2.10',
    'embassy-2.9',
    'gcc',
    'gnustep-old',
    'gtk-engines',
    'gtk-engines2',
    'inherit',
    'jakarta-commons',
    'java-pkg',
    'java-utils',
    'kde-base',
    'kde-i18n',
    'kde-source',
    'kmod',
    'koffice-i18n',
    'motif',
    'mozilla',
    'myth',
    'pax-utils',
    'pcmcia',
    'perl-post',
    'php',
    'php-2',
    'php-ext',
    'php-ext-base',
    'php-ext-pecl',
    'php-ext-source',
    'php-lib',
    'php-pear',
    'php-sapi',
    'php5-sapi',
    'php5-sapi-r1',
    'php5-sapi-r2',
    'php5-sapi-r3',
    'tla',
    'webapp-apache',
    'xfree'))

    __doc__ = "scan for deprecated eclass usage\n\ndeprecated eclasses:%s\n" % \
        ", ".join(sorted(blacklist))

    def feed(self, pkgs, reporter):
        for pkg in pkgs:
            yield pkg
            bad = self.blacklist.intersection(pkg.data["_eclasses_"])
            if bad:
                reporter.add_report(DeprecatedEclass(pkg, bad))


class DeprecatedEclass(Result):
    """pkg uses an eclass that is deprecated/abandoned"""
    
    __slots__ = ("category", "package", "version", "eclasses")
    
    def __init__(self, pkg, eclasses):
        Result.__init__(self)
        self._store_cpv(pkg)
        self.eclasses = tuple(sorted(eclasses))

    def to_str(self):
        return "%s/%s-%s: deprecated eclasses [ %s ]" % (self.category, 
            self.package, self.version, ", ".join(self.eclasses))

    def to_xml(self):
        return \
"""<check name="%s">
    <category>%s</category>
    <package>%s</package>
    <version>%s</version>
    <msg>deprecated eclass usage- %s</msg>
</check>""" % (self.__class__.__name__, self.category, self.package,
    self.version, ", ".join(self.eclasses))
