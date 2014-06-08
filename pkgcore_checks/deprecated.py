# Copyright: 2006-2011 Brian Harring <ferringb@gmail.com>
# License: BSD/GPL2

from pkgcore_checks.base import Template, versioned_feed, Result


class DeprecatedEAPI(Result):
    """pkg's EAPI is deprecated according to repo metadata"""

    __slots__ = ("category", "package", "version", "eapi")
    threshold = versioned_feed

    def __init__(self, pkg):
        Result.__init__(self)
        self._store_cpv(pkg)
        self.eapi = pkg.eapi

    @property
    def short_desc(self):
        return "uses deprecated EAPI: %s" % (self.eapi,)


class DeprecatedEAPIReport(Template):

    feed_type = versioned_feed
    known_results = (DeprecatedEAPI,)

    __doc__ = "scan for deprecated EAPIs"

    def feed(self, pkg, reporter):
        if str(pkg.eapi) in pkg.repo.config.eapis_deprecated:
            reporter.add_report(DeprecatedEAPI(pkg))


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
        'bash-completion',
        'darcs',
        'db4-fix',
        'debian',
        'embassy-2.10',
        'embassy-2.9',
        'gems',
        'git',
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
        'mozconfig', 'mozconfig-2',
        'mozcoreconf',
        'motif',
        'mozilla',
        'myth',
        'pcmcia',
        'perl-post',
        'php',
        'php-2',
        'php-ext',
        'php-ext-base',
        'php-ext-pecl', 'php-ext-pecl-r1',
        'php-ext-source', 'php-ext-source-r1',
        'php-lib',
        'php-pear',
        'php-sapi',
        'php5-sapi',
        'php5-sapi-r1',
        'php5-sapi-r2',
        'php5-sapi-r3',
        'qt3', 'qt4',
        'ruby',
        'ruby-gnome2',
        'tla',
        'webapp-apache',
        'x-modular',
        'xfree',
    ))

    __doc__ = "scan for deprecated eclass usage\n\ndeprecated eclasses:%s\n" % \
        ", ".join(sorted(blacklist))

    def feed(self, pkg, reporter):
        bad = self.blacklist.intersection(pkg.inherited)
        if bad:
            reporter.add_report(DeprecatedEclass(pkg, bad))
