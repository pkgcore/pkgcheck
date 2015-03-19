# Copyright: 2006-2011 Brian Harring <ferringb@gmail.com>
# License: BSD/GPL2

from snakeoil.mappings import ImmutableDict

from pkgcheck.base import Template, versioned_feed, Result


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
        self.eclasses = eclasses

    @property
    def short_desc(self):
        eclass_migration = []
        for old_eclass, new_eclass in sorted(self.eclasses.iteritems()):
            if new_eclass:
                update_path = 'migrate to %s' % (new_eclass,)
            else:
                update_path = 'no replacement'
            eclass_migration.append('%s (%s)' % (old_eclass, update_path))

        return "uses deprecated eclass(es): [ %s ]" % ', '.join(eclass_migration)


class DeprecatedEclassReport(Template):

    feed_type = versioned_feed
    known_results = (DeprecatedEclass,)

    blacklist = ImmutableDict({
        '64-bit': None,
        'bash-completion': 'bash-completion-r1',
        'boost-utils': None,
        'darcs': None,
        'distutils': 'distutils-r1',
        'db4-fix': None,
        'debian': None,
        'embassy-2.10': None,
        'embassy-2.9': None,
        'gems': 'ruby-fakegem',
        'git': 'git-r3',
        'git-2': 'git-r3',
        'gcc': None,
        'gnustep-old': None,
        'gtk-engines': None,
        'gtk-engines2': None,
        'inherit': None,
        'jakarta-commons': None,
        'java-pkg': None,
        'java-utils': None,
        'kde-base': None,
        'kde-i18n': None,
        'kde-source': None,
        'kmod': None,
        'koffice-i18n': None,
        'mono': 'mono-env',
        'mozconfig': None,
        'mozconfig-2': 'mozconfig-3',
        'mozcoreconf': 'mozcoreconf-2',
        'motif': None,
        'mozilla': None,
        'myth': None,
        'pcmcia': None,
        'perl-post': None,
        'php': None,
        'php-2': None,
        'php-ext': None,
        'php-ext-base': None,
        'php-ext-pecl': None,
        'php-ext-pecl-r1': 'php-ext-pecl-r2',
        'php-ext-source': None,
        'php-ext-source-r1': 'php-ext-source-r2',
        'php-lib': None,
        'php-pear': 'php-pear-r1',
        'php-sapi': None,
        'php5-sapi': None,
        'php5-sapi-r1': None,
        'php5-sapi-r2': None,
        'php5-sapi-r3': None,
        'python': 'python-r1 / python-single-r1 / python-any-r1',
        'python-distutils-ng': 'python-r1 + distutils-r1',
        'qt3': None,
        'qt4': 'qt4-r2',
        'ruby': 'ruby-ng',
        'ruby-gnome2': 'ruby-ng-gnome2',
        'tla': None,
        'vim': None,
        'webapp-apache': None,
        'x-modular': 'xorg-2',
        'xfree': None,
    })

    __doc__ = "scan for deprecated eclass usage\n\ndeprecated eclasses:%s\n" % \
        ", ".join(sorted(blacklist))

    def feed(self, pkg, reporter):
        bad = set(self.blacklist.keys()).intersection(pkg.inherited)
        if bad:
            eclasses = ImmutableDict({old: new for old, new in self.blacklist.iteritems() if old in bad})
            reporter.add_report(DeprecatedEclass(pkg, eclasses))
