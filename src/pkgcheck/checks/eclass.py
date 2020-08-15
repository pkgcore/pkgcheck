from snakeoil.mappings import ImmutableDict
from snakeoil.process.spawn import spawn_get_output
from snakeoil.strings import pluralism

from .. import base, results, sources
from . import Check


class DeprecatedEclass(results.VersionResult, results.Warning):
    """Package uses an eclass that is deprecated/abandoned."""

    def __init__(self, eclasses, **kwargs):
        super().__init__(**kwargs)
        self.eclasses = tuple(eclasses)

    @property
    def desc(self):
        eclass_migration = []
        for old_eclass, new_eclass in self.eclasses:
            if new_eclass:
                update_path = f'migrate to {new_eclass}'
            else:
                update_path = 'no replacement'
            eclass_migration.append(f'{old_eclass} ({update_path})')

        es = pluralism(eclass_migration, plural='es')
        eclasses = ', '.join(eclass_migration)
        return f'uses deprecated eclass{es}: [ {eclasses} ]'


class DuplicateEclassInherits(results.VersionResult, results.Warning):
    """An ebuild directly inherits the same eclass multiple times.

    Note that this will flag ebuilds that conditionalize global metadata by
    package version (or some other fashion) while inheriting the same eclass
    under both branches, e.g. conditional live ebuilds. In this case, shared
    eclasses should be loaded in a separate, unconditional inherit call.
    """

    def __init__(self, eclasses, **kwargs):
        super().__init__(**kwargs)
        self.eclasses = tuple(eclasses)

    @property
    def desc(self):
        eclasses = ', '.join(self.eclasses)
        es = pluralism(self.eclasses, plural='es')
        return f'duplicate inherits for eclass{es}: {eclasses}'


class EclassUsageCheck(Check):
    """Scan packages for various eclass-related issues."""

    known_results = frozenset([DeprecatedEclass, DuplicateEclassInherits])

    blacklist = ImmutableDict({
        '64-bit': None,
        'autotools-multilib': 'multilib-minimal',
        'autotools-utils': None,
        'base': None,
        'bash-completion': 'bash-completion-r1',
        'boost-utils': None,
        'clutter': 'gnome2',
        'cmake-utils': 'cmake',
        'confutils': None,
        'darcs': None,
        'distutils': 'distutils-r1',
        'db4-fix': None,
        'debian': None,
        'embassy-2.10': None,
        'embassy-2.9': None,
        'epatch': (
            'eapply from EAPI 6',
            lambda pkg: 'eapply' in pkg.eapi.bash_funcs),
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
        'ltprune': None,
        'user': 'acct-user/acct-group packages',
        'versionator': (
            'ver_* functions from EAPI 7',
            lambda pkg: 'ver_cut' in pkg.eapi.bash_funcs),
        'vim': None,
        'webapp-apache': None,
        'x-modular': 'xorg-2',
        'xfconf': None,
        'xfree': None,
    })

    def feed(self, pkg):
        deprecated = []
        duplicates = set()
        inherited = set()

        for eclass in pkg.inherit:
            if eclass not in inherited:
                inherited.add(eclass)
            else:
                duplicates.add(eclass)

        for eclass in inherited.intersection(self.blacklist):
            replacement = self.blacklist[eclass]
            if isinstance(replacement, tuple):
                replacement, conditional = replacement
                if not conditional(pkg):
                    continue
            deprecated.append((eclass, replacement))

        if duplicates:
            yield DuplicateEclassInherits(sorted(duplicates), pkg=pkg)
        if deprecated:
            yield DeprecatedEclass(sorted(deprecated), pkg=pkg)


class EclassBashSyntaxError(results.EclassResult, results.Error):
    """Bash syntax error in the related eclass."""

    def __init__(self, lineno, error, **kwargs):
        super().__init__(**kwargs)
        self.lineno = lineno
        self.error = error

    @property
    def desc(self):
        return f'{self.eclass}: bash syntax error, line {self.lineno}: {self.error}'


class EclassCheck(Check):
    """Scan eclasses for various issues."""

    scope = base.eclass_scope
    _source = sources.EclassRepoSource
    known_results = frozenset([EclassBashSyntaxError])

    def feed(self, eclass):
        ret, err = spawn_get_output(['bash', '-n', eclass.path], collect_fds=(2,))
        if ret != 0 and err:
            lineno = 0
            error = []
            for line in err:
                path, line, msg = line.split(': ', 2)
                lineno = line[5:]
                error.append(msg.strip('\n'))
            error = ': '.join(error)
            yield EclassBashSyntaxError(lineno, error, eclass=eclass)
