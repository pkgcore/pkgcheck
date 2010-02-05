# Copyright: 2006 Marien Zwart <marienz@gentoo.org>
# License: BSD/GPL2


from pkgcore_checks import reporters, base

pkgcore_plugins = {
    'configurable': [
        reporters.xml_reporter,
        reporters.plain_reporter,
        reporters.fancy_reporter,
        reporters.multiplex_reporter,
        base.Whitelist,
        base.Blacklist,
        base.Suite,
        ],
    }
