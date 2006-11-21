# Copyright: 2006 Marien Zwart <marienz@gentoo.org>
# License: GPL2


from pkgcore_checks import reporters, pcheck

pkgcore_plugins = {
    'configurable': [
        reporters.xml_reporter,
        reporters.plain_reporter,
        reporters.fancy_reporter,
        reporters.multiplex_reporter,
        pcheck.Whitelist,
        pcheck.Blacklist,
        pcheck.Suite,
        ],
    }
