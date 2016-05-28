=============
Release Notes
=============

See ChangeLog for full commit logs; this is summarized and major changes.

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
