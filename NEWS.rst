=============
Release Notes
=============

---------------------------
pkgcheck 0.7.0 (2019-11-08)
---------------------------

- BadInsIntoCheck: Skip reporting insinto calls using subdirs since the related
  commands don't support installing files into subdirs.

- PerlCheck: Run by default if perl and deps are installed otherwise skip unless
  explicitly enabled.

- SourcingError: Add specific result for ebuilds that fail sourcing due to
  metadata issues.

- Fix git --commits option restriction.

---------------------------
pkgcheck 0.6.9 (2019-11-04)
---------------------------

- MissingSlash: Avoid some types of false positives where the path variable is
  used to create a simple string, but not as a path directly.

- BadPerlModuleVersion: Add support for verifying Gentoo's perl module
  versioning scheme -- not run by default since it requires various perl
  dependencies.

- BadCommitSummary: Also allow "${CATEGORY}/${P}:" prefixes.

- MetadataError: Fix suppressing duplicate results due to multiprocess usage.

- VisibleVcsPkg: Collapse profile reports for non-verbose mode.

- Use replacement character for non-UTF8 characters while decoding author,
  committer, and message fields from git logs.

- pkgcheck scan: Try parsing target arguments as restrictions before falling
  back to using path restrictions.

- EmptyProject: Check for projects with no members in projects.xml.

- StaticSrcUri: Check if SRC_URI uses static values for P or PV instead of the
  dynamic, variable equivalents.

- MatchingChksums: Check for distfiles that share the same checksums but have
  different names.

- pkgcheck scan: Parallelize checks for targets passed in via cli args.

- Sort versioned package results under package scanning scope so outputted
  results are deterministic when scanning against single packages similar to
  what the output is per package when running scans at a category or repo
  level.

---------------------------
pkgcheck 0.6.8 (2019-10-06)
---------------------------

- pkgcheck scan: Add -t/--tasks option to limit the number of async tasks that
  can run concurrently. Currently used to limit the number of concurrent
  network requests made.

- Repository level checks are now run in parallel by default.

- Fix iterating over git commits to fix git-related checks.

---------------------------
pkgcheck 0.6.7 (2019-10-05)
---------------------------

- pkgcheck scan: All scanning scopes now run checks in parallel by default for
  multi-core systems. For repo/category scope levels parallelism is done per
  package while for package/version scope levels parallelism is done per
  version. The -j/--jobs option was also added to allow controlling the amount
  of processes used when scanning, by default it's set to the number of CPUs
  the target system has.

- pkgcheck cache: Add initial cache subcommand to support updating/removing
  caches used by pkgcheck. This allows users to forcibly update/remove caches
  when they want instead of pkgcheck only handling the process internally
  during the scanning process.

- Add specific result keywords for metadata issues relating to various package
  attributes instead of using the generic MetadataError for all of them.

- Drop check for PortageInternals as the last usage was dropped from the tree.

- Add EmptyCategoryDir and EmptyPackageDir results to warn when the gentoo repo
  has empty category or package directories that people removing packages
  forgot to handle.

- Drop HttpsAvailableCheck and its related HttpsAvailable result. The network
  checks should now support dynamically pinging sites to test for viability.

- Port network checks to use the requests module for http/https requests so
  urllib is only used for ftp URLs.

---------------------------
pkgcheck 0.6.6 (2019-09-24)
---------------------------

- HttpsUrlAvailable: Check http URLs for https availability (not run by
  default).

- MissingLicenseRestricts: Skip RESTRICT="mirror" for packages lacking SRC_URI.

- DeprecatedEapiCommand: Check for deprecated EAPI commands (e.g. dohtml usage in EAPI 6).

- BannedEapiCommand: Check for banned EAPI commands (e.g. dohtml usage in EAPI 7).

- StableRequestCheck: Use ebuild modification events instead of added events to
  check for stabilization.

- Add support for filtering versioned results to only check the latest VCS and
  non-VCS packages per slot.

- MissingSlotDep: Fix dep slot determination by using use flag stripped dep
  atoms instead of unversioned atoms.

- Add HomepageUrlCheck and FetchablesUrlCheck network-based checks that check
  HOMEPAGE and SRC_URI urls for various issues and require network access so
  they aren't run by default. The ``--net`` option must be specified in order
  to run them.

---------------------------
pkgcheck 0.6.5 (2019-09-18)
---------------------------

- InvalidUseFlags: Flag invalid USE flags in IUSE.

- UnknownUseFlags: Use specific keyword result for unknown USE flags in IUSE
  instead of MetadataError.

- pkgcheck scan: Add ``info`` alias for -k/--keywords option and rename
  errors/warnings aliases to ``error`` and ``warning``.

- Add Info result type and mark a several non-warning results as info level
  (e.g. RedundantVersion and PotentialStable).

- MissingLicenseRestricts: Flag restrictive license usage missing required
  RESTRICT settings.

- MissingSlotDepCheck: Properly report missing slotdeps for atom with use deps.

- pkgcheck scan: Add ``all`` alias for -c/--checks option.

- MissingSignOff: Add initial check for missing commit message sign offs.

- InvalidLicenseHeader: Add initial license header check for the gentoo repo.

- BadCommitSummary: Add initial commit message summary formatting check.

---------------------------
pkgcheck 0.6.4 (2019-09-13)
---------------------------

- Add FormatReporter supporting custom format string output.

- pkgcheck scan: Drop --metadata-xsd-required option since the related file is
  now bundled with pkgcore.

- Add CsvReporter for outputting results in CSV format.

- pkgcheck scan: Add --commits option that use local git repo changes to
  determine scan targets.

- DroppedUnstableKeywords: Disregard when stable target keywords exist.

- LocalUSECheck: Add test for USE flags with reserved underscore character.

- PathVariablesCheck: Drop 'into' from prefixed dir functions list to avoid
  false positives in comments.

- MissingUnpackerDepCheck: Drop checks for jar files since most are being
  directly installed and not unpacked.

- Make gentoo repo checks work for external gentoo repos on systems with a
  configured gentoo system repo.

- UnknownFile: Flag unknown files in package directories for the gentoo repo.

---------------------------
pkgcheck 0.6.3 (2019-08-30)
---------------------------

- PathVariablesCheck: Flag double path prefix usage on uncommented lines only
  to avoid some types of false positives.

- BadInsIntoCheck: flag ``insinto /usr/share/doc/${PF}`` usage for recent EAPIs
  as it should be replaced by docinto and dodoc [-r] calls.

- BadInsIntoCheck: Drop old cron support.

- Skip global checks when running at cat/pkg/version restriction levels for
  ``pkgcheck scan``. Also, skip package level checks that require package set
  context when running at a single version restriction level.

---------------------------
pkgcheck 0.6.2 (2019-08-26)
---------------------------

- TreeVulnerabilitiesCheck: Restrict to checking against the gentoo repo only.

- Allow explicitly selected keywords to properly enable their related checks if
  they must be explicitly enabled.

- UnusedMirrorsCheck: Ignore missing checksums for fetchables that will be
  caught by other checks.

- pkgcheck replay: Add support for replaying JsonStream reporter files.

- Add initial JsonStream reporter as an alternative to the pickle reporters for
  serializing and deserializing result objects.

- Add support for comparing and hashing result objects.

- Fix triggering metadata.xml maintainer checks only for packages.

---------------------------
pkgcheck 0.6.1 (2019-08-25)
---------------------------

- NonexistentProfilePath: Change from warning to an error.

- Fix various XML result initialization due to missing attributes.

- MissingUnpackerDepCheck: Fix matching against versioned unpacker deps.

- Rename BadProto keyword to BadProtocol.

---------------------------
pkgcheck 0.6.0 (2019-08-23)
---------------------------

- Profile data is now cached on a per repo basis in ~/.cache/pkgcore/pkgcheck
  (or wherever the related XDG cache environment variables point) to speed up
  singular package scans. These caches are checked and verified for staleness
  on each run and are enabled by default.

  To forcibly disable profile caches include ``--profile-cache n`` or similar
  as arguments to ``pkgcheck scan``.

- When running against a git repo, the historical package removals and
  additions are scanned from ``git log`` and used to populate virtual repos
  that enable proper stable request checks and nonexistent/outdated blocker
  checks. Note that initial runs where these repos are being built from scratch
  can take a minute or more depending on the system; however, subsequent runs
  shouldn't take much time to update the cached repos.

  To disable git support entirely include ``--git-disable y`` or similar as
  arguments to ``pkgcheck scan``.

- zshcomp: Add initial support for keyword, check, and reporter completion.

- Enhance support for running against unconfigured, external repos. Now
  ``pkgcheck scan`` should be able to handle scanning against relevant paths to
  unknown repos passed to it or against a repo with no arguments passed that
  the current working directory is currently within.

New keywords/checks
===================

- BadFilename: Flag SRC_URI targets that use unspecific ${PN}.ext filenames.

- HomepageInSrcUri: Flag ${HOMEPAGE} usage in SRC_URI.

- MissingConditionalTestRestrict: Flag missing ``RESTRICT="!test? ( test )"``.

- InvalidProjectMaintainer: Flag packages specifying non-existing project as
  maintainer.

- PersonMaintainerMatchesProject: Flag person-type maintainer matching existing
  projects.

- NonGentooAuthorsCopyright: Flag ebuilds with copyright stating owner other
  than "Gentoo Authors" in the main gentoo repo.

- AcctCheck: Add various checks for acct-* packages.

- MaintainerWithoutProxy: Flag packages with a proxyless proxy maintainer.

- StaleProxyMaintProject: Flag packages using proxy-maint maintainer without
  any proxied maintainers.

- BinaryFile: Flag binary files found in the repository.

- DoublePrefixInPath: Flag ebuilds using two consecutive paths including
  EPREFIX.

- PythonReport: Add various python eclasses related checks.

- ObsoleteUri: Flag obsolete URIs (github/gitlab) that should be updated.

- VisibilityReport: Split NonsolvableDeps into stable, dev, and exp results
  according to the status of the profile that triggered them.

- GitCommitsCheck: Add initial check support for unpushed git commits. This
  currently includes the following keywords: DirectNoMaintainer,
  DroppedStableKeywords, DroppedUnstableKeywords, DirectStableKeywords, and
  OutdatedCopyright.

- MissingMaintainer: Flag packages missing a maintainer (or maintainer-needed
  comment) in metadata.xml.

- EqualVersions: Flag ebuilds that have semantically equal versions.

- UnnecessarySlashStrip: Flag ebuilds using a path variable that strips a
  nonexistent slash (usually due to porting to EAPI 7).

- MissingSlash: Flag ebuilds using a path variable missing a trailing slash
  (usually due to porting to EAPI 7).

- DeprecatedChksum: Flag distfiles using outdated checksum hashes.

- MissingRevision: Flag packages lacking a revision in =cat/pkg dependencies.

- MissingVirtualKeywords: Flag virtual packages with keywords missing from
  their dependencies.

- UnsortedKeywords: Flag packages with unsorted KEYWORDS.

- OverlappingKeywords: Flag packages with overlapping arch and ~arch KEYWORDS.

- DuplicateKeywords: Flag packages with duplicate KEYWORD entries.

- InvalidKeywords: Flag packages using invalid KEYWORDS.

---------------------------
pkgcheck 0.5.4 (2017-09-22)
---------------------------

- Add MetadataXmlEmptyElement check for empty elements in metadata.xml files.

- Add BadProfileEntry, UnknownProfilePackages, UnknownProfilePackageUse, and
  UnknownProfileUse checks that scan various files in a repo's profiles
  directory looking for old packages and/or USE flags.

- Merge replay functionality into pkgcheck and split the commands into 'scan',
  'replay', and 'show' subcommands with 'scan' still being the default
  subcommand so previous commandline usage for running pkgcheck remains the
  same for now.

- Add 'errors' and 'warnings' aliases for the -k/--keywords option, e.g. if you
  only want to scan for errors use the following: pkgcheck -k errors

- Fallback to the default repo if not running with a configured repo and one
  wasn't specified.

- Add PortageInternals check for ebuilds using a function or variable internal
  to portage similar to repoman.

- Add HttpsAvailable check for http links that should use https similar
  to repoman.

- Add DuplicateFiles check for duplicate files in FILESDIR.

- Add EmptyFile check for empty files in FILESDIR.

- Add AbsoluteSymlink check similar to repoman's.

- Add UnusedInMasterLicenses, UnusedInMasterEclasses,
  UnusedInMasterGlobalFlags, and UnusedInMasterMirrors reports that check if an
  overlay is using the related items from the master repo that are unused there
  (meaning they could be removed from the master soon).

- Add initial json reporter that outputs newline-delimited json for report
  objects.

- Add BadFilename check for unspecific filenames such as ${PV}.tar.gz or
  v${PV}.zip that can be found on raw github tag archive downloads.

- GPL2/BSD dual licensing was dropped to BSD as agreed by all contributors.

- Add check for REQUIRED_USE against default profile USE which flags packages
  with default USE settings that don't satisfy their REQUIRED_USE for each
  profile scanned.

- Add -k/--keywords option to only check for certain keywords.

- Add UnusedEclasses check.

- Drop --profiles-disable-deprecated option, deprecated profiles are skipped by
  default now and can be enabled or disabled using the 'deprecated' argument to
  -p/--profiles similar to the stable, dev, and exp keywords for profile
  scanning.

- Add UnusedProfileDirs check that will output all profile dirs that aren't
  specified as a profile in profiles.desc or aren't sourced by any as a parent.

- Add python3.6 support and drop python3.3 support.

- Add UnnecessaryManifest report for showing unnecessary manifest entries for
  non-DIST targets on a repo with thin manifests enabled.

- Collapse -c/--check and -d/--disable-check into -c/--checks option using the
  same extended comma toggling method used for --arches and --profiles options.

- Add support for checking REQUIRED_USE for validity.

- Drop -o/--overlayed-repo support and rely on properly configured masters.

- Add UnknownLicenses report for unknown licenses listed in license groups.

- Add support for running checks of a certain scope using -S/--scopes, e.g. to
  run all repo scope checks on the gentoo repo use the following command:
  pkgcheck -r gentoo -S repo

- Add UnusedMirrorsCheck to scan for unused third party mirrors.

- Add UnknownCategories report that shows categories that aren't listed in a
  repo's (or its masters) categories.

- Update deprecated eclasses list.

- Drop restriction on current working directory for full repo scans. Previously
  pkgcheck had to be run within a repo, now it should be able to run from
  anywhere against a specified repo.

---------------------------
pkgcheck 0.5.3 (2016-05-29)
---------------------------

* Fix new installs using pip.

---------------------------
pkgcheck 0.5.2 (2016-05-28)
---------------------------

* Replace libxml2 with lxml-based validator for glep68 schema validation.

* UseAddon: Use profile-derived implicit USE flag lists instead of pre-EAPI 5
  hacks. This also improves the unused global USE flag check to look for unused
  USE_EXPAND flags.

* Add various repo-level sanity checks for profile and arch lists.

* Output reports for ~arch VCS ebuilds as well, previously only vcs ebuilds
  with stable keywords would display warnings.

* Large reworking of profile and arch addon options. In summary, the majority
  of the previous options have been replaced with -a/--arches and -p/--profiles
  that accept comma separated lists of targets to enable or disable. The
  keywords stable, dev, and exp that related to the sets of stable,
  development, and experimental profiles from the targetted repo can also be
  used as --profiles arguments.

  For example, to scan all stable profiles use the following::

    pkgcheck -p stable

  To scan all profiles except experimental profiles (note the required use of
  an equals sign when starting the argument list with a disabled target)::

    pkgcheck -p=-exp

  See the related man page sections for more details.

* Officially support python3 (3.3 and up).

* Add initial man page generated from argparse info.

* Migrate from optparse to argparse, usability-wise there shouldn't be any
  changes.

* Drop ChangeLog file checks, the gentoo repo moved to git so ChangeLogs are
  not in the repo anymore.

---------------------------
pkgcheck 0.5.1 (2015-08-10)
---------------------------

* Remove portdir references, if you use a custom config file you may need to
  update 'portdir' references to use 'gentoo' instead or whatever your main
  repo is.

---------------------------
pkgcheck 0.5.0 (2015-04-01)
---------------------------

* Suppress possible memory exhaustion cases for visibility checks due to
  transitive use flag dependencies.

* Project, python module, and related scripts renamed from pkgcore-checks (or
  in the case of the python module pkgcore_checks) to pkgcheck.

* Add --profile-disable-exp option to skip experimental profiles.

* Make the SizeViolation check test individual files in $FILESDIR, not the
  entire $FILESDIR itself.

* Make UnusedLocalFlags scan metadata.xml for local use flags instead of the
  deprecated repo-wide use.local.desc file.

* Stable arch related checks (e.g. UnstableOnly) now default to using only the
  set of stable arches defined by profiles.desc.

* Add check for deprecated EAPIs.

* Conflicting manifests chksums scanning was added.

* Removed hardcoded manifest hashes list, use layout.conf defined list of
  required hashes (didn't exist till ~5 years after the check was written).

* Update pkgcore API usage to move away from deprecated functionality.

----------------------------------
pkgcore-checks 0.4.15 (2011-10-27)
----------------------------------

* pkgcore-checks issue #2; if metadata.dtd is required but can't be fetched,
  suppress metadata_xml check.  If the check must be ran (thus unfetchable
  metadata.dtd should be a failure), pass --metadata-dtd-required.

* pkgcore-checks now requires pkgcore 0.7.3.

* fix racey test failure in test_addons due to ProfileNode instance caching.

* fix exception in pkg directory checks for when files directory
  doesn't exist.

* cleanup of deprecated api usage.

----------------------------------
pkgcore-checks 0.4.14 (2011-04-24)
----------------------------------

* Updated compatibility w/ recent snakeoil/pkgcore changes.

* deprecated eclasses list was updated.

* LICENSE checks for virtual/* are now suppressed.

----------------------------------
pkgcore-checks 0.4.13 (2010-01-08)
----------------------------------

* fix to use dep scanning in visibility where it was missing use deps that
  can never be satisfied for a specific profile due to use masking/forcing.

* more visibility optimizations; Grand total in combination w/ optimziations
  leveled in snakeoil/pkgcore since pkgcore-checks 0.4.12 released, 58%
  faster now.

* ignore unstated 'prefix' flag in conditionals- much like bootstrap, its'
  the latest unstated.

* added a null reporter for performance testing.

----------------------------------
pkgcore-checks 0.4.12 (2009-12-27)
----------------------------------

* corner case import error in metadata_xml scan for py3k is now fixed; if
  you saw urllib.urlopen complaints, this is fixed.

* >snakeoil-0.3.4 is now required for sdist generation.

* visibility scans now use 22% less memory (around 130MB on python2.6 x86_64)
  and is about 3% faster.

----------------------------------
pkgcore-checks 0.4.11 (2009-12-20)
----------------------------------

* minor speedup in visibility scans- about 3% faster now.

* fix a traceback in deprecated from when portage writes the ebuild cache out
  w/out any _eclasses_ entry.

* fix a rare traceback in visibility scans where a virtual metapkg has zero
  matches.

----------------------------------
pkgcore-checks 0.4.10 (2009-12-14)
----------------------------------

* fix a bug where use deps on metapkgs was invalidly being flagged.

---------------------------------
pkgcore-checks 0.4.9 (2009-11-26)
---------------------------------

* fix a bug in test running- bzr_verinfo isn't generated for pkgcore-checks
  in sdist (no need), yet build_py was trying to regenerate it.  Basically
  broke installation on machines that lacked bzr.

---------------------------------
pkgcore-checks 0.4.8 (2009-11-26)
---------------------------------

* experimental py3k support.

* test runner improvements via depending on snakeoil.distutils_extensions.

---------------------------------
pkgcore-checks 0.4.7 (2009-10-26)
---------------------------------

* fix invalid flagging of use deps on PyQt4 for ia64; basically PyQt4[webkit]
  is valid due to a pkg level masked use reversal... the checking code however
  wasn't doing incremental expansion itself..  Same could occur for forced use.

---------------------------------
pkgcore-checks 0.4.6 (2009-10-22)
---------------------------------

* fix a bug in tristate use evaluation of potential USE combinations.
  Roughly, if a flag is masked *and* forced, the result is it's masked.

* compatibility fixes for pkgcore 0.5; 0.5 isn't required, but advised.

---------------------------------
pkgcore-checks 0.4.5 (2008-11-07)
---------------------------------

* verify whether or not a requested use state is actually viable when profile
  masking/forcing is taken into account.

---------------------------------
pkgcore-checks 0.4.4 (2008-10-21)
---------------------------------

* EAPI2 support for checking use/transitive use deps.

* ticket 216; basically portage doesn't always write out _eclasses_ entries
  in the cache- if they're empty, it won't.  pkgcore-checks visibility vcs
  eclass tests assumed otherwise- this is now fixed.

* pcheck now only outputs the number of tests it's running if --debug is
  enabled.

---------------------------------
pkgcore-checks 0.4.3 (2008-03-18)
---------------------------------

* ticket 8; false positive unused global USE flags due to not stripping '+-'
  from iuse defaults.

* ticket 7: tune down metadata xml checks verbosity.

* dropped ModularXPortingReport; no longer needed.

----------------------------------
pkgcore-checks 0.4.2 (2007-12-15)
----------------------------------

* minor release to be EAPI=1 compatible wrt IUSE defaults

----------------------------------
pkgcore-checks 0.4.1 (2007-07-16)
----------------------------------

* fixed ticket 90; NonExistantDeps occasionally wouldn't report later versions
  of an offender.

* --disable-arches option; way to specifically disable an arch (blacklisting)
  instead of having to specify all arches.

-------------------------------
pkgcore-checks 0.4 (2007-06-06)
-------------------------------

* update to use snakeoil api.

* Add check to metadata_check.DependencyReport for self-blocking atoms; for
  example, if dev-util/diffball RDEPEND has !dev-util/diffball.

* ticket 82; Fix BadProto result object so it has proper threshold.

* Fix class serialization bug in RestrictsReport.

* profile loadup optimization; pkgcore weakly caches the intermediate nodes,
  pcheck's profile loadup however specifically released the profiles every
  looping; now it temporarily holds onto it, thus allowing the caching to kick
  in.  Among other things, cuts file reads down from 1800 to around around 146.

--------------------
pkgcore-checks 0.3.5
--------------------

* addition of __attrs__ to base.Result classes; use this if __slots__ doesn't
  suffice for listing the attrs to pickle.

* Thanks to Michael Sterret for pointing it out; tweak cleanup scan so that it
  notes 1.12 overshadows 1.11 (stable keywords overshadow earlier unstable
  versions): for example-
  1.11: ~x86 ~amd64
  1.12: x86 ~amd64

--------------------
pkgcore-checks 0.3.4
--------------------

* treat pkg.restrict as a depset.

--------------------
pkgcore-checks 0.3.3
--------------------

* drop digest specific checks; portage now prunes digests on sync regardless
  of whether or not the repo is m2 pure; thus, no way to detect if a missing
  digest is actually a screwup in the repo, or if it's portage being 'special'.
  May re-add the checks down the line, currently however removing them for
  the common case.

* back down check for files directory if manifest2; manifest2 glep didn't
  specify that files directory could be dropped, but portage has deviated there.
  Since been backed down, but getting ahead so we don't need an intermediate
  release when they try it again.

* added check for missing metadata.xml; refactored common error class selection
  logic into base class.

--------------------
pkgcore-checks 0.3.2
--------------------

* correct tracebacks when dealing with a few result objects from repo_metadata

--------------------
pkgcore-checks 0.3.1
--------------------

* makes StaleUnstable abide by --arches; ticket 59 (thanks leio).
* stop complaining about empty keywords, since they're now allowed instead of
  using -\*.

------------------
pkgcore-checks 0.3
------------------

* heavy refactoring of reporter subsystem, and clean up of check results.
  Better messages, better output for normal usage.  to_xml() methods were
  dropped (XmlReporter handles it on it's own), same for to_str() in favor
  of short_desc and long_desc attributes.
* whitespace checks now output one result for each classification for an
  ebuild, instead of emitting reports for each line.
* all remaining 'info' statements are pushed to stderr now.
* new PickleStream reporter; used to serialize check results, and flush the
  stream out stdout.  If you need to get at the data generated, this is the
  sanest way to do it (alternatives require trying to deserialize what a
  reporter does, thus losing data).
* added new tool replay-pcheck-stream; used to replay a pickle stream through
  alternative reporters.

------------------
pkgcore-checks 0.2
------------------

* invocation args have changed- please see readme for details of how to
  use pcheck.
* test suite added; not yet complete coverage, but 90% of the way there.
* --list-checks output format is fair bit more human-readable now.
* better support for overlays (should work fine with appropriate commandline
  options supplied)
* optimizations, and performance regression fixes; fair bit faster then .1.
* new checks can be added via pkgcore 0.2 plugins cache.
* UI improvements; color, and human readable output.
* --xml option was dropped, use --reporter to specify the desired reporter,
  and --list-reporters to see what reporters are available
* added --enable, --disable options to prune add/remove specific checks from
  the run.
* add config based 'suites' that can be ran; basically, sets of tests/targets
  to run via pcheck.  See README for details.
* whitespace checks.

------------------
pkgcore-checks 0.1
------------------

* inital release
