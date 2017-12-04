from .. import reporters, base

pkgcore_plugins = {
    'configurable': [
        reporters.json_reporter,
        reporters.xml_reporter,
        reporters.plain_reporter,
        reporters.fancy_reporter,
        reporters.picklestream_reporter,
        reporters.binarypicklestream_reporter,
        reporters.multiplex_reporter,
        base.Whitelist,
        base.Blacklist,
        base.Suite,
        ],
    }
