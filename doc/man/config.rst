Config file support
===================

Config files are supported by ``pkgcheck scan`` from any of four locations.
Listed in order of increasing precedence these include the following:

- system config -- ``/etc/pkgcheck/pkgcheck.conf``
- user config -- ``${XDG_CONFIG_HOME}/pkgcheck/pkgcheck.conf``
- user config -- ``~/.config/pkgcheck/pkgcheck.conf``
- repo config -- ``metadata/pkgcheck.conf`` inside an ebuild repo (only
  considered when the current directory is inside the repo, or when specified
  using ``--repo`` option)
- custom config -- specified via the ``--config`` option

Any settings from a config file with higher precedence will override matching
settings from a config file with a lower precedence, e.g. repo settings
override both user and system settings. Note that command line options override
any matching config file setting.

In terms of file structure, basic INI formatting is required and allows
creating a default section (DEFAULT) for system-wide settings or repo-specific
sections. The INI key-value pairs directly relate to the available
long-options supported by ``pkgcheck scan`` and their related values. See the
following examples for how certain config settings affect scanning:

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

Custom checksets can also be configured via the CHECKSETS section. In essence,
a checkset is an alias for a group of checks or keywords which can either be
enabled or disabled. Configured checkset names can then be used with the
``pkgcheck scan -C/--checkset`` option enabling scanning for configured, custom
sets of results. See the following examples for how to configure them:

- Assign all python-related checks to the ``python`` checkset::

    [CHECKSETS]
    python = PythonCheck,PythonCompatCheck

- Checksets also support disabling, e.g. assign all results related to
  ManifestCheck except DeprecatedChksum to the ``manifests`` checkset::

    [CHECKSETS]
    manifests = ManifestCheck,-DeprecatedChksum
