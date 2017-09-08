from snakeoil.mappings import ImmutableDict
from snakeoil.strings import pluralism

from pkgcheck.base import Template, versioned_feed, Warning


class DeprecatedEAPI(Warning):
    """Package's EAPI is deprecated according to repo metadata."""

    __slots__ = ("category", "package", "version", "eapi")
    threshold = versioned_feed

    def __init__(self, pkg):
        super(DeprecatedEAPI, self).__init__()
        self._store_cpv(pkg)
        self.eapi = str(pkg.eapi)

    @property
    def short_desc(self):
        return "uses deprecated EAPI: %s" % (self.eapi,)


class DeprecatedEAPIReport(Template):
    """Scan for deprecated EAPIs."""

    feed_type = versioned_feed
    known_results = (DeprecatedEAPI,)


    def feed(self, pkg, reporter):
        if str(pkg.eapi) in pkg.repo.config.eapis_deprecated:
            reporter.add_report(DeprecatedEAPI(pkg))


class DeprecatedEclass(Warning):
    """Package uses an eclass that is deprecated/abandoned."""

    __slots__ = ("category", "package", "version", "eclasses")
    threshold = versioned_feed

    def __init__(self, pkg, eclasses):
        super(DeprecatedEclass, self).__init__()
        self._store_cpv(pkg)
        self.eclasses = tuple(sorted(eclasses.iteritems()))

    @property
    def short_desc(self):
        eclass_migration = []
        for old_eclass, new_eclass in self.eclasses:
            if new_eclass:
                update_path = 'migrate to %s' % (new_eclass,)
            else:
                update_path = 'no replacement'
            eclass_migration.append('%s (%s)' % (old_eclass, update_path))

        return "uses deprecated eclass%s: [ %s ]" % (
            pluralism(eclass_migration, plural='es'), ', '.join(eclass_migration))


class DeprecatedEclassReport(Template):

    feed_type = versioned_feed
    known_results = (DeprecatedEclass,)

    blacklist = ImmutableDict({
        '64-bit': None,
        'autotools-multilib': 'multilib-minimal',
        'autotools-utils': None,
        'base': None,
        'bash-completion': 'bash-completion-r1',
        'boost-utils': None,
        'clutter': 'gnome2',
        'confutils': None,
        'darcs': None,
        'distutils': 'distutils-r1',
        'db4-fix': None,
        'debian': None,
        'embassy-2.10': None,
        'embassy-2.9': None,
        'fdo-mime': 'xdg-utils',
        'games': None,
        'gems': 'ruby-fakegem',
        'git': 'git-r3',
        'git-2': 'git-r3',
        'gcc': None,
        'gnustep-old': None,
        'gpe': None,
        'gst-plugins-bad': 'gstreamer',
        'gst-plugins-base': 'gstreamer',
        'gst-plugins-good': 'gstreamer',
        'gst-plugins-ugly': 'gstreamer',
        'gst-plugins10': 'gstreamer',
        'gtk-engines': None,
        'gtk-engines2': None,
        'inherit': None,
        'jakarta-commons': None,
        'java-pkg': None,
        'java-utils': None,
        'kde-base': None,
        'kde-i18n': None,
        'kde4-meta-pkg': 'kde5-meta-pkg',
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
        'xfconf': None,
        'xfree': None,
    })

    __doc__ = "Scan for deprecated eclass usage.\n\ndeprecated eclasses: %s\n" % \
        ", ".join(sorted(blacklist))

    def feed(self, pkg, reporter):
        bad = set(self.blacklist.keys()).intersection(pkg.inherited)
        if bad:
            eclasses = ImmutableDict({old: new for old, new in self.blacklist.iteritems() if old in bad})
            reporter.add_report(DeprecatedEclass(pkg, eclasses))
