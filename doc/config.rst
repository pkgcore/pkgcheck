Config file support
===================

Config files are supported by ``pkgcheck scan`` from any of three locations.
Listed in order of increasing precedence these include the following:

- system config -- /etc/pkgcheck/pkgcheck.conf
- user config -- ~/.config/pkgcheck/pkgcheck.conf
- repo config -- metadata/pkgcheck.conf inside an ebuild repo

Any settings from a config file with higher precedence will override matching
settings from a config file with a lower precedence, e.g. repo settings
override both user and system settings. Note that command line options override
any matching config file setting.

In terms of file structure, basic INI formatting is required and allows
creating a default section for system-wide settings or repo-specific sections.
The INI key-value pairs directly relate to the available long-options supported
by ``pkgcheck scan`` and their related values. See the following examples for
how certain config settings affect scanning:

- Disable selected checks by default::

    [DEFAULT]
    checks = -UnstableOnlyCheck,-RedundantVersionCheck

- Disable showing info level results for the gentoo repo::

    [gentoo]
    keywords = -info

- Restrict scanning to the amd64 and x86 arches/profiles for the gentoo repo::

    [gentoo]
    arches = amd64,x86

- Enable network checks that require Internet access for the gentoo repo using
  a custom timeout of 15 seconds::

    [gentoo]
    net =
    timeout = 15

- Use the JSON reporter by default and disable all cache usage::

    [DEFAULT]
    reporter = JsonReporter
    cache = no

- Set the default repo to target::

    [DEFAULT]
    repo = my_overlay
