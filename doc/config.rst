Config file support
===================

Config files are supported by ``pkgcheck scan`` from any of three locations.
Listed in order of increasing precedence these include the following:

- system config -- /etc/pkgcheck/pkgcheck.conf
- user config -- ~/.config/pkgcheck/pkgcheck.conf
- repo config -- metadata/pkgcheck.conf inside an ebuild repo

Any settings from a config file with higher precedence will override matching
settings from a config file with a lower precedence, e.g. repo settings
override both user and system settings.

In terms of file structure, basic INI formatting is required and allows
creating a default section for system-wide settings or repo-specific sections.
The INI key-value pairs directly relate to the available long-options supported
by ``pkgcheck scan`` and their related values. See the following examples for
how certain config settings affect scanning runs.

Example 1
---------
Disable selected checks by default for all scanning runs::

    [DEFAULT]
    checks = -UnstableOnlyCheck,-RedundantVersionCheck

Example 2
---------
Disable showing info level results for the gentoo repo::

    [gentoo]
    keywords = -info

Example 3
---------
Restrict scanning to the amd64 and x86 arches/profiles for the gentoo repo::

    [gentoo]
    arches = amd64,x86

Example 4
---------
Enable network checks that require Internet access for the gentoo repo using
a custom timeout of 15 seconds::

    [gentoo]
    net =
    timeout = 15

Example 5
---------
Use the JSON reporter by default for scanning output and disable all cache usage::

    [DEFAULT]
    reporter = JsonReporter
    cache = no

Example 6
---------
Set the default repo to target when scanning::

    [DEFAULT]
    repo = my_overlay
