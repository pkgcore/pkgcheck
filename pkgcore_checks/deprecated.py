# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: BSD/GPL2

from pkgcore_checks.base import Template, versioned_feed, Result


class DeprecatedEclass(Result):
    """pkg uses an eclass that is deprecated/abandoned"""

    __slots__ = ("category", "package", "version", "eclasses")
    threshold = versioned_feed

    def __init__(self, pkg, eclasses):
        Result.__init__(self)
        self._store_cpv(pkg)
        self.eclasses = tuple(sorted(eclasses))

    @property
    def short_desc(self):
        return "uses deprecated eclasses [ %s ]" % ', '.join(self.eclasses)


class DeprecatedEclassReport(Template):

    feed_type = versioned_feed
    known_results = (DeprecatedEclass,)

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

    def feed(self, pkg, reporter):
        bad = self.blacklist.intersection(pkg.data.get("_eclasses_", ()))
        if bad:
            reporter.add_report(DeprecatedEclass(pkg, bad))
