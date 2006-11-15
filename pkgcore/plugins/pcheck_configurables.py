# Copyright: 2006 Marien Zwart <marienz@gentoo.org>
# License: GPL2


from pkgcore_checks import base, pcheck

pkgcore_plugins = {
    'configurable': [
        base.xml_reporter,
        base.plain_reporter,
        base.fancy_reporter,
        base.multiplex_reporter,
        pcheck.Whitelist,
        pcheck.Blacklist,
        pcheck.Suite,
        ],
    }
