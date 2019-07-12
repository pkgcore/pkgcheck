"""Extra default config sections from pkgcheck."""

from pkgcore.config import basics

from .. import base

pkgcore_plugins = {
    'global_config': [{
        'repo': basics.ConfigSectionFromStringDict({
            'class': 'pkgcheck.base.Scope',
            'scopes': str(base.repository_scope),
            }),
        'no-arch': basics.ConfigSectionFromStringDict({
            'class': 'pkgcheck.base.Blacklist',
            'patterns': 'unstable_only stablereq imlate',
            }),
        'all': basics.ConfigSectionFromStringDict({
            'class': 'pkgcheck.base.Blacklist',
            'patterns': '',
            }),
        }],
    }
