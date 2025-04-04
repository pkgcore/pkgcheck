=============
Release Notes
=============

-----------------------------
pkgcheck 0.10.34 (2025-04-04)
-----------------------------

**New Checks:**

- NonConsistentTarUsage: detect ``tar`` invocations missing the ``-f`` argument
  (Arthur Zamarin, #709)

- TooManyCrates: flag packages with more than 300 CRATES (Arthur Zamarin)

**Check Updates:**

- OutdatedBlocker: extend the threshold for outdated blockers from 2 years to 4
  years (Sam James)

- DeprecatedInsinto: add support for paths related to shell completion and
  systemd (Arthur Zamarin)

- DirectStableKeywords: exclude ``sec-keys/*`` and ``virtual/*`` categories
  from this check (Arthur Zamarin, #719)

- RequiredUseDefaults: skip all USE flags prefixed with ``cpu_flags_`` (Arthur
  Zamarin)

- git: suggest clearing the pkgcheck cache when encountering a ``git log``
  error (Martin Mokry, #729)

- PythonCompatUpdate: ignore ``*t`` (freethreading) Python targets
  (Arthur Zamarin, Michał Górny, #711, #732)

- DeadUrl: prevent crashes when servers return invalid UTF-8 data (Arthur
  Zamarin)

- PathVariablesCheck: expand the list of names checked for path variable issues
  (Arthur Zamarin)

- MissingRemoteId: exclude URIs used for fetching ``-crates`` or ``-deps``
  tarballs from this check (Arthur Zamarin)

-----------------------------
pkgcheck 0.10.33 (2024-12-04)
-----------------------------

- fix compatibility with Python 3.12.8 (Michał Górny)

-----------------------------
pkgcheck 0.10.32 (2024-11-23)
-----------------------------

**Checks Updates:**

- various Python checks: recognize ``dev-lang/pypy`` as a Python
  interpreter package (Michał Górny, #708)

- EclassManualDepsCheck: update for the new ``rust`` eclass:
  direct dependencies on ``dev-lang/rust`` and ``dev-lang/rust-bin``;
  ``RUST_OPTIONAL`` variable (Michał Górny, #718)

- PythonPackageNameCheck: enforce the stricter PyPI package naming
  policy that requires using lowercase names with hyphens (Michał Górny,
  #717)

-----------------------------
pkgcheck 0.10.31 (2024-09-06)
-----------------------------

- fix compatibility with tree-sitter 0.23 (Arthur Zamarin)

- bash completion: improve path handling (Arthur Zamarin)

**New Checks:**

- OldPackageNameDep: check for dependency using previously moved package's name
  (Arthur Zamarin, #659, #694)

- BadDependency: catch ``:=`` slot operator in PDEPEND (Arthur Zamarin, #660)

**Checks Updates:**

- DistutilsNonPEP517Build: handle false positives when defined by eclass
  (Arthur Zamarin)

- PythonCompatCheck: add whitelist for backports (Arthur Zamarin)

- EmptyGlobalAssignment: ignore empty KEYWORDS (Arthur Zamarin, #695)

-----------------------------
pkgcheck 0.10.30 (2024-05-18)
-----------------------------

- pyproject: fix python compat with snakeoil (Lucio Sauer, #678)

- NetAddon: fix ftp call with ``--timeout 0`` (Lucio Sauer, #678)

- NewerEAPIAvailable: handle better when no eclasses EAPI  (Arthur Zamarin, #679)

- fix compatibility with newest version of tree-sitter (Arthur Zamarin)

-----------------------------
pkgcheck 0.10.29 (2024-03-28)
-----------------------------

- drop bundling of tree-sitter-bash (Arthur Zamarin)

- use flit as build backend for pkgcheck (Arthur Zamarin)

- PkgBadlyFormedXml: change level to error instead of a warning (Arthur Zamarin,
  #668)

- git addon: support user global gitignore (Arthur Zamarin, #671, #672)

**New checks:**

- NewerEAPIAvailable: committing new ebuilds with old EAPI (Arthur Zamarin, #666)

-----------------------------
pkgcheck 0.10.28 (2024-03-01)
-----------------------------

- docs: Add intersphinx linkages (Brian Harring, #658)

**New checks:**

- VariableOrderWrong: Enforce skel.ebuild variable order (Anthony Ryan, #645)

**Fixed bugs:**

- git: fix issues with no-copies (Arthur Zamarin, Sam James, #663, #664)

- addons.net: suppress urllib3 import warnings (Anna "CyberTailor", #661)

-----------------------------
pkgcheck 0.10.27 (2024-01-25)
-----------------------------

- Dockerfile: introduce ``pkgcheck`` docker, created on release, which should
  provide stable and tested environment to run, for example in CI (Arthur
  Zamarin)

- Test pkgcheck with Python 3.12 and 3.13 (Sam James, #567)

**New checks:**

- UnstatedIuse: check for unstated IUSE in "?" dependencies (Arthur Zamarin)

- SandboxCallCheck: check for invalid sandbox funciton calls (Arthur Zamarin,
  #644)

- OldPackageName: check for package named after old package name (Arthur
  Zamarin, #650)

- RepositoryCategories: check for fundamental category issues in the repository
  layout (Brian Harring, #656)

**Fixed bugs:**

- pyproject.toml: add runtime dependency on setuptools for Python 3.12 (Arthur
  Zamarin)

- MissingInherits: add some special variables to exclude list (Arthur Zamarin)

- UnusedInherits: add whitelist for weak usage by another eclass, for example
  conditional automagic inherit (Arthur Zamarin)

- GitCommitsCheck: fix tarfile Python 3.12 compatibility (Alfred Wingate, #638)

- MissingRemoteId: improve gitlab matching rules (Alfred Wingate, #636, #637)

- OutdatedProfilePackage: don't warn when version was removed not long ago
  (Arthur Zamarin)

- DeprecatedDep: fix mishandling of slotted deprecates (Arthur Zamarin, #642)

- DependencyMoved: show better error for dependency on pkgmove (Arthur Zamarin,
  #649)

- compatibilty: remove reliance on ``repo.category_dirs`` (Brian Harring, #656)

-----------------------------
pkgcheck 0.10.26 (2023-10-08)
-----------------------------

- tree-sitter-bash: use and bundle the latest version of the bash grammar. This
  version is capable to parse all the bash code that was used in gentoo
  repository, meaning various false positives or parsing errors were fixed.
  (Arthur Zamarin)

- git addon: pass options to disable finding copies (Sam James, #618)

- git addon: add helping message on failure of git remote setup (Arthur
  Zamarin, #608)

**New checks:**

- VariableScopeCheck: add check for usage of prohibited variables in global
  scope (Arthur Zamarin, #607)

- VariableScopeCheck: BROOT is allowed also in ``pkg_{pre,post}{inst,rm}``
  (Ulrich Müller, #609)

- GlobDistdir: check for unsafe filename expansion with ``${DISTDIR}`` (Arthur
  Zamarin, #610)

- EclassManualDepsCheck: check for missing manual deps for specific eclasses
  (Arthur Zamarin, #616)

- UnstableSrcUri: check for known unstable ``SRC_URI`` sources (Arthur Zamarin,
  #599)

- network: add codeberg remote-id (Thomas Bracht Laumann Jespersen, #620)

- EmptyGlobalAssignment: check for empty global assignments (Arthur Zamarin,
  #629)

- SelfAssignment: check for global scope self assignments (Arthur Zamarin, #629)

- BannedPhaseCall: detect calls of phase functions directly in ebuilds (Arthur
  Zamarin, #627)

- VariableShadowed: check to detect shadowed variable assignments (Arthur
  Zamarin, #623)

- DuplicateFunctionDefinition: check for duplicate global functions (Arthur
  Zamarin, #624)

- BannedEapiCommand: also check for ``has_version --host-root`` and
  ``best_version --host-root`` in EAPI>=7 (Arthur Zamarin, #630)

- BannedEapiCommand: add some extra user and group commands (Arthur Zamarin)

**Fixed bugs:**

- RedundantLongDescription: lower too short threshold (Arthur Zamarin, #614)

- tests.test_pkgcheck_scan: fix issues with xdist testing (Arthur Zamarin)

-----------------------------
pkgcheck 0.10.25 (2023-07-29)
-----------------------------

- scan: add ``--git-remote`` option to select remote used for git operations
  (Arthur Zamarin, #601)

**New checks:**

- RustCheck: check for suboptimal ``-`` ``CRATES`` separator (Arthur Zamarin,
  #589)

- RustCheck: check for suboptimal ``cargo_crate_uris`` call (Arthur Zamarin,
  #589)

- OutdatedProfilePackage: show unknown packages in profile with last match date
  (Arthur Zamarin, #590)

- SrcUriFilenameDotPrefix: new check for ``SRC_URI`` filenames with dot prefix
  (Arthur Zamarin, #592)

- RubyCompatCheck: new check for new ``USE_RUBY`` compatible values, similar to
  ``PythonCompatCheck`` (Arthur Zamarin, #595)

- OldPythonCompat: check for old ``PYTHON_COMPAT`` in commit's modified ebuilds
  (Arthur Zamarin, #596)

- RepoManifestHashCheck: check for deprecated repo ``manifest-hashes`` (Arthur
  Zamarin, #598)

- DeprecatedManifestHash: check for deprecated checksums in Manifest files
  (Arthur Zamarin, #598)

- PerlCheck: optional check for versioned virtual perl dependencies (Arthur
  Zamarin, #597)

**Fixed bugs:**

- MissingInherits: exclude ``@USER_VARIABLEs`` (Arthur Zamarin, #575)

- scan: fix unknown exit checkset during initial config load (Arthur Zamarin,
  #594)

- GitPkgCommitsCheck: fix failure during compute of environment (Arthur Zamarin)

-----------------------------
pkgcheck 0.10.24 (2023-05-17)
-----------------------------

**New checks:**

- UnknownCategoryDirs: enable for overlays and ignore scripts dir (Arthur
  Zamarin, #564)

- PythonFetchableCheck: rewrite check to reuse ``PYPI_SDIST_URI_RE`` (Michał
  Górny, #569)

- PythonFetchableCheck: include ``PYPI_PN`` opportunities in
  ``PythonInlinePyPIURI`` (Michał Górny, #568, #569)

- PythonFetchableCheck: restore filename check in pypi.eclass default case
  (Michał Górny, #572)

- MissingEAPIBlankLine: new optional check for missing blank after EAPI (Arthur
  Zamarin, #570, #571)

- StaleLiveCheck: new check for stale live ebuilds EAPI version (Arthur
  Zamarin, #578)

**Fixed bugs:**

- GitPkgCommitsCheck: fix modification check for added ebuilds in packages set
  (Arthur Zamarin, #563)

- SrcUriChecksumChange: fix false positive with new ebuilds (Arthur Zamarin,
  #553)

- fix config loading when ``XDG_CONFIG_HOME`` is defined (Alberto Gireud, #573)

- scan: fix unknown checkset during initial config load for checksets declared
  in repository config (Arthur Zamarin, #576)

- ProfilesCheck: fix handling of profiles with ``-*`` declared in ``packages``
  (Arthur Zamarin, #577)

----------------------------
pkgcheck 0.10.23 (2023-03-06)
----------------------------

- scan: use ``NO_COLOR`` environment variable to disable colors instead of
  ``NOCOLOR`` (Ulrich Müller, https://bugs.gentoo.org/898230)

**New checks:**

- network: add ``kde-invent`` remote-id (Sam James, #551)

- EbuildSemiReservedName: check for usage of semi-reserved names in ebuilds
  (Arthur Zamarin, #552)

- PythonPEP517WithoutRevbump: check for DISTUTILS_USE_PEP517 addition or
  removal without revision bump (Sam James, #556)

- EAPIChangeWithoutRevbump: check for EAPI change without revision bump (Arthur
  Zamarin, #558)

**Fixed bugs:**

- StableRequestCheck: ignore versions which aren't keyworded for stable arches
  (Arthur Zamarin, #544)

- PythonMissingSCMDependency: update to new canonical package names of SCM
  python packages (Arthur Zamarin)

----------------------------
pkgcheck 0.10.22 (2023-02-20)
----------------------------

**New checks:**

- PythonInlinePyPIURI: new check for using inline PyPI URI instead of via new
  ``pypi.eclass`` (Michał Górny, #543)

**Fixed bugs:**

- SuspiciousSrcUriChange: fix false positives for ``SRC_URI`` mirror expanded
  (Arthur Zamarin, #542)

- SuspiciousSrcUriChange: fix false positives on user configuration with
  default mirror (Arthur Zamarin, #548, #549)

- InvalidCommitTag: fix false positives with advanced formatted ``Fixes`` and
  ``Reverts`` tags (Arthur Zamarin, #546)

- UnusedInherits: fix false positives for eclasses defining special global
  variables such as ``SRC_URI`` and ``HOMEPAGE`` (Arthur Zamarin, #361, #540)

----------------------------
pkgcheck 0.10.21 (2023-02-04)
----------------------------

**New checks:**

- ProvidedEclassInherit: new check for inheriting provided eclases (Arthur
  Zamarin, #509)

- MissingInherits: don't show for functions defined in ebuild (Arthur Zamarin,
  #513)

- EclassUsageCheck: check for setting user variables in ebuilds (Arthur
  Zamarin, #518)

- VariableScopeCheck: Disallow ``D`` and ``ED`` in ``pkg_postinst`` (Ulrich
  Müller, #523)

- ProfilesCheck: check for unknown ``ARCH`` in make.defaults (Arthur Zamarin,
  #525)

- ProfilesCheck: check for unknown ``USE`` & ``IUSE_IMPLICIT`` in make.defaults
  (Arthur Zamarin, #525)

- ProfilesCheck: check for unknown ``USE_EXPAND_*`` in make.defaults (Arthur
  Zamarin, #525)

- ProfilesCheck: check ``USE_EXPAND_VALUES_*`` in make.defaults (Arthur
  Zamarin, #525)

- ProfilesCheck: check missing values for implicit in make.defaults (Arthur
  Zamarin, #525)

- ArchesMisSync: check for missync between ``arch.list`` and ``arches.desc``
  (Arthur Zamarin, #529)

- SrcUriChecksumChange: check for changing checksums of distfiles without
  distfile rename (Arthur Zamarin, #497)

- SuspiciousSrcUriChange: check for changing URLs of distfiles without distfile
  rename (Arthur Zamarin, #497)

- InvalidMetadataRestrict: check for invalid restricts in metadata.xml (Arthur
  Zamarin, #532)

- PythonPackageNameCheck: check for mismatching python package names (Michał
  Górny, Arthur Zamarin, #534)

- PythonCheck: check for missing BDEPEND on setuptools_scm or alike (Arthur
  Zamarin, #534)

**Fixed bugs:**

- git checks: include revision for old name during ``git mv`` (Arthur Zamarin,
  #511)

- Profile caching: use REPO profile base to improve cache hits (Daniel M.
  Weeks, #528)

- MissingManifest: fix behavior under thick repos (Arthur Zamarin, #530)

- scan: suppress non-error results in quiet mode (Arthur Zamarin, #413)

- RdependChange: skip when revbumped in same batch (Arthur Zamarin, #459)

- scan: fix no attribute live or slot for commits scanning (Arthur Zamarin,
  #380)

- setup.py: fix usage of absolute path, which fixes compatibility with new
  setuptools (Arthur Zamarin, https://bugs.gentoo.org/892938)

----------------------------
pkgcheck 0.10.20 (2022-12-29)
----------------------------

- MissingRemoteIdCheck: give ready ``<remote-id/>`` sample (Michał Górny, #500)

- Format code with ``black`` (Arthur Zamarin)

----------------------------
pkgcheck 0.10.19 (2022-11-26)
----------------------------

- scan: add support to disable colors using environment variable ``NOCOLOR``
  (Arthur Zamarin)

- Use refactored and pure setuptools as build backend for pkgcheck. This
  includes removal of old development scripts and setup.py hacks, in favor of
  a simple commands or using the Makefile. (Arthur Zamarin, #494)

- docs: use new snakeoil extension for sphinx (Arthur Zamarin, #494)

- release: add support for other linux architectures wheels, including
  aarch64, ppc64le, and s390x (Arthur Zamarin, #494)

- PythonCheck: remove obsolete pypy packages (Michał Górny, #495)

- PythonCheck: stop warning about eclass use on ``python:2.7`` deps (Michał
  Górny, #495)

----------------------------
pkgcheck 0.10.18 (2022-11-09)
----------------------------

Special thanks is given to Sam James, for continues support during all
development, bringing ideas, testing and improving, and especially proofreading
and improving all docs, texts and help messages. Every release is better thanks
to him.

- Network checks: fix wrong attributes ("blame") shown when same URL is checked
  (#403, Arthur Zamarin)

- BetterCompressionCheck: new check for suggesting better compression URI for
  gitlab and github distfiles (#483, Arthur Zamarin)

- ExcessiveLineLength: report lines longer than 120 characters (with multiple
  exception rules) (#480, Arthur Zamarin)

- MissingRemoteIdCheck: new check for suggesting missing remote-ids, inferred
  from HOMEPAGE and SRC_URI (#486, Arthur Zamarin)

- DoCompressedFilesCheck: new check for calling ``doman``, ``newman``, and
  ``doinfo`` with compressed files (#485, Arthur Zamarin)

- AcctCheck: determine dynamic ID range from repository file
  ``metadata/qa-policy.conf`` rather than static hardcoded values in pkgcheck
  (#489, Arthur Zamarin)

- UnquotedVariable: fix false positives with ``declaration_command`` and
  ``unset_command`` (Arthur Zamarin)

- VirtualWithSingleProvider: new check for virtual packages with a single
  provider across all versions, which should be deprecated (#484, Arthur
  Zamarin)

- VirtualProvidersCheck: new check for virtual packages defining build
  dependencies (#484, Arthur Zamarin)

- NonPosixHeadTailUsage: new check for non-POSIX compliant usage of ``head``
  and ``tail`` (#491, Arthur Zamarin)

- drop Python 3.8 support (Arthur Zamarin)

----------------------------
pkgcheck 0.10.17 (2022-10-14)
----------------------------

- EbuildReservedCheck: catch declaration of phase hooks as reserved (Arthur
  Zamarin, #458)

- GitPkgCommitsCheck: cleanup temporary directories after use, so unless
  pkgcheck crashes, the ``/tmp/tmp-pkgcheck-*.repo`` directories will be
  cleaned (Arthur Zamarin, #449)

- GitPkgCommitsCheck: fix crashes when checking commit range which has multiple
  commits dropping versions from same package (Arthur Zamarin, #460, #461)

- GitPkgCommitsCheck: fix crashes with checking EAPI of ebuilds because of
  missing ``profiles`` directory (Arthur Zamarin, #461)

- PythonCheck: when checking for matching ``python_check_deps``, use
  ``python_gen_cond_dep`` for ebuilds inheriting ``python-single-r1``
  (Arthur Zamarin)

- RedundantVersionCheck: consider profile masks for redundancy check (Arthur
  Zamarin, #466, #465)

- contrib/emacs: run flycheck only when buffer is saved (Alfred Wingate, #464)

- GitCommitsCheck: run all checks sequentially on main process, to mitigate
  race conditions during parallel calls to ``git log`` (Arthur Zamarin, #326,
  #454)

- PythonCheck: warn about use of ``distutils-r1`` non-PEP517 mode (Michał
  Górny, #467)

----------------------------
pkgcheck 0.10.16 (2022-10-04)
----------------------------

- StaticSrcUri: handle more cases of static URI and offer replacements (Arthur
  Zamarin, #453)

- scan: respect jobs count from MAKEOPTS (Arthur Zamarin, #449)
  https://bugs.gentoo.org/799314

- ProfilesCheck: new check for no-op ``package.mask`` entries which negates
  non-existent mask in parents profiles (Arthur Zamarin, #456)

----------------------------
pkgcheck 0.10.15 (2022-09-16)
----------------------------

- MissingInherits: fix false positives with ``unset`` (Arthur Zamarin, #432)

- DescriptionCheck: change long length threshold to 80 (Arthur Zamarin)

- BadCommitSummary: version check should be ignored for ``acct-*`` packages
  (Arthur Zamarin, #434)

- ReservedNameCheck: update rules for usage of reserved, that both usage
  *and* definitions reserved names and not only defining is prohibited
  (Arthur Zamarin, #437)

- GitPkgCommitsCheck: add prefix and suffix for created temporary files (Arthur
  Zamarin, #441)

- FlycheckReporter: split multiple line results into separate reported lines,
  (Arthur Zamarin, #443)

- RedundantVersionCheck: add ``--stable-only`` option, to consider redundant
  versions only within stable (Arthur Zamarin, #438)

- network: add ``savannah`` and ``savannah-nongnu`` remote-ids (Sam James, #446)

- network: add ``freedesktop-gitlab`` and ``gnome-gitlab`` remote-ids (Matt
  Turner, #445)

----------------------------
pkgcheck 0.10.14 (2022-08-16)
----------------------------

- sdist file now includes ``contrib/`` directory (Arthur Zamarin)

----------------------------
pkgcheck 0.10.13 (2022-08-15)
----------------------------

- Add new ``FlycheckReporter`` which is used for flycheck integration (On the
  fly syntax checking for GNU Emacs) (Arthur Zamarin, Maciej Barć, #420)

- PythonMissingDeps: check for missing ``BDEPEND="${DISTUTILS_DEPS}"`` in
  PEP517 python ebuilds with ``DISTUTILS_OPTIONAL`` set (Sam James, #389)

- PythonHasVersionUsage: new check for using ``has_version`` inside
  ``python_check_deps`` (Arthur Zamarin, #401)

- PythonHasVersionMissingPythonUseDep: new check for missing ``PYTHON_USEDEP``
  in calls to ``python_has_version`` or ``has_version`` (Arthur Zamarin, #401)

- PythonAnyMismatchedHasVersionCheck: new check for mismatch between calls to
  ``python_has_version`` and ``has_version`` against calls to
  ``python_gen_any_dep`` in dependencies (Arthur Zamarin, #401)

- Fix calls to ``git`` on system repositories when ``safe.directory`` is
  enforced (Arthur Zamarin, #421)

- Fix and port pkgcheck to Python 3.11 (Sam James, #424)

- Bump snakeoil and pkgcore dependencies (Sam James, #425)

- UseFlagWithoutDeps (Gentoo repository only): new check for USE flags, which
  don't affect dependencies and because they provide little utility (Arthur
  Zamarin, #428)

- StableRequestCheck: add ``--stabletime`` config option for specifying the
  time before a version is flagged by StableRequestCheck (Emily Rowlands, #429)

- MisplacedWeakBlocker: new check for pure-DEPEND weak blockers (Arthur
  Zamarin, #430)

----------------------------
pkgcheck 0.10.12 (2022-07-30)
----------------------------

- UnquotedVariable: new check for problematic unquoted variables in ebuilds and
  eclasses (Thomas Bracht Laumann Jespersen, #379)

- DroppedUnstableKeywords: set priority to Error (Arthur Zamarin, #397)

- PythonGHDistfileSuffix: exempt commit snapshots from requiring ``.gh`` suffix
  (Michał Górny, #398)

- SizeViolation: add check for total size of ``files/`` directory and improve
  texts (Michał Górny, #406)

- MetadataUrlCheck: add sourcehut remote-id (Sam James, #415)

- MetadataUrlCheck: add hackage remote-id (Sam James, #416)

----------------------------
pkgcheck 0.10.11 (2022-05-26)
----------------------------

- EclassReservedName and EbuildReservedName: new check for usage of function or
  variable names which are reserved for the package manager by PMS (Arthur
  Zamarin, #378)

- UrlCheck: skip verification of URLs with an unknown protocol. Such issues are
  already detected by DeadUrl (Michał Górny, #384)

- PythonGHDistfileSuffix: new check for python packages which contain pypi
  remote-id and fetch from GitHub should use ``.gh`` suffix for tarballs
  (Michał Górny, #383)

- MetadataUrlCheck: perform the check for the newest version instead of the
  oldest (Michał Górny, #390)

- InvalidRemoteID: new check for validity of remote-id in ``metadata.xml``
  (Michał Górny, #387, #386)

- Network checks: fixed filtering for latest versions (Michał Górny, #392)

- Scan commits: fix ebuild parsing in old repo, fixing most of the checks done
  by ``--commits`` mode (Arthur Zamarin, #393)

----------------------------
pkgcheck 0.10.10 (2022-05-14)
----------------------------

- Unpin tree-sitter version needed by pkgcheck (Michał Górny)

- Use @ECLASS_VARIABLE instead of @ECLASS-VARIABLE (Ulrich Müller, #360)

- PythonCheckCompat: use ``python_*.desc`` from masters (jan Anja, #334)

- Properly close opened resources (Thomas Bracht Laumann Jespersen, #364)

- Use system's ``libtree-sitter-bash`` if available (Thomas Bracht Laumann
  Jespersen, #367)

- Add bash completion for pkgcheck (Arthur Zamarin, #371)

- MetadataVarCheck: check LICENSE doesn't contain variables (Thomas Bracht
  Laumann Jespersen, #368)

- New check EendMissingArgCheck: check all calls to ``eend`` have an argument
  (Thomas Bracht Laumann Jespersen, #365)

- EclassUsageCheck: new checks for usage of deprecated variables or function
  (Arthur Zamarin, #375)

----------------------------
pkgcheck 0.10.9 (2021-12-25)
----------------------------

- AcctCheck: extend allowed UID/GID range to <750.

- fix compatibility with setuptools 60.

----------------------------
pkgcheck 0.10.8 (2021-09-26)
----------------------------

- remove tests for profiles with no replacement (no longer reported
  by pkgcore).

- derive eclass cache version from pkgcore.

----------------------------
pkgcheck 0.10.7 (2021-09-03)
----------------------------

- bump eclass cache version after API changes in pkgcore 0.12.7.

----------------------------
pkgcheck 0.10.6 (2021-09-02)
----------------------------

- add a check for calling EXPORT_FUNCTIONS before further inherits.

- InheritsCheck: process @PROVIDES recursively.

- InheritsCheck: enable by default.

----------------------------
pkgcheck 0.10.5 (2021-08-16)
----------------------------

- EapiCheck: Report using stable keywords on EAPI listed as testing.

- RepoProfilesCheck: Enhance LaggingProfileEapi not to rely on string
  comparison between EAPI versions, and enable it for repositories
  other than ::gentoo.

- RepoProfilesCheck: Report profiles using banned or deprecated EAPI.

- GitCommitMessageCheck: Relax the check to allow the version to be
  preceded by "v".

----------------------------
pkgcheck 0.10.4 (2021-08-04)
----------------------------

- Ignore global user and system git config (#336).

- Skip git cache usage when not running on the default branch (#335).

- Use location-based unique IDs for cache dirs in order to force separate repos
  with the name ID to use different caches (#321).

----------------------------
pkgcheck 0.10.3 (2021-06-30)
----------------------------

- BadCommitSummary: Don't flag revision bumps missing pkg versions.

----------------------------
pkgcheck 0.10.2 (2021-06-29)
----------------------------

- BadCommitSummary: Only allow "cat/pn: " prefixes.

- GitCommitMessageCheck: Flag pkg adds missing versions in the summary (#298).

- AcctCheck: Restrict to the gentoo repo (#327).

----------------------------
pkgcheck 0.10.1 (2021-05-28)
----------------------------

- ProfilesCheck: Add initial UnknownProfileUseExpand result support.

- LicenseCheck: Add initial DeprecatedLicense result support (#325).

- LicenseCheck: Rename MissingLicenseFile result to UnknownLicense for consistency.

- IuseCheck: Add initial BadDefaultUseFlags result (#314 and #315).

- DeprecatedDep: Verify all matching packages are deprecated (#317).

- MisplacedEclassVar: Only pull pre-inherit vars for targeted eclasses (#324).

- PythonCompatCheck: Fix python-single-r1 ebuilds using python_target deps (#323).

----------------------------
pkgcheck 0.10.0 (2021-05-22)
----------------------------

- Add initial EAPI 8 support.

- DependencyCheck: Add InvalidIdepend result.

- PythonCompatCheck: Fix treating python3.10 as newer than python3.9 (#320).

---------------------------
pkgcheck 0.9.7 (2021-03-27)
---------------------------

- pkgcheck scan: Fix raw repo creation for overlays.

---------------------------
pkgcheck 0.9.6 (2021-03-26)
---------------------------

- Add support for identifying misplaced eclass spec variables (#309).

---------------------------
pkgcheck 0.9.5 (2021-03-20)
---------------------------

- Don't include bash parser shared library in tarball and build platform
  dependent wheels with the library prebuilt.

---------------------------
pkgcheck 0.9.4 (2021-03-19)
---------------------------

- MetadataVarCheck: Add KEYWORDS verification (#303).

- GitAddon: Store commit timestamp instead of date string.

- MissingLocalUseDesc: Add explicit result for local use flags missing
  descriptions.

- DirectStableKeywords: Skip acct-group and acct-user categories (#308).

- PackageMetadataXmlCheck: Support proxied metadata.xml attribute.

---------------------------
pkgcheck 0.9.3 (2021-03-12)
---------------------------

- MisplacedVariable: New keyword flagging variables used outside their defined
  scope.

- ReadonlyVariable: New keyword flagging read-only variables that are globally
  assigned (#300).

- pkgcheck.utils: Fallback to assuming libstdc++ exists for build_library()
  (#299).

---------------------------
pkgcheck 0.9.2 (2021-03-05)
---------------------------

- Update tree-sitter-bash to language version 13 to work with
  >=tree-sitter-0.19.0.

---------------------------
pkgcheck 0.9.1 (2021-03-05)
---------------------------

- Support newline-separated values for lists in addition to comma-separated in
  pkgcheck configs.

- pkgcheck scan: Bundle and load a config defining a GentooCI checkset matching
  Gentoo CI error keywords.

- pkgcheck scan: Add --staged support for targeting staged git changes to
  generate restrictions.

- pkgcheck: Suppress pkgcore-specific help options that should generally be
  avoided by users but is required internally.

---------------------------
pkgcheck 0.9.0 (2021-02-23)
---------------------------

- pkgcheck ci: Add initial subcommand for CI-specific usage (e.g. used by
  pkgcheck-action).

- EclassCheck: force bash error output to use the C locale.

- Officially export Result class in addition to all specific result
  keywords/classes for API usage which can be useful for type
  hinting purposes.

- pkgcheck scan: Respect version-level scan scope targets (#293).

- pkgcheck scan: Allow additive args for --exit. This allows adding
  keywords to the default set (via '+Keyword') that trigger exit
  failures without having to explicitly specify the 'error' set as
  well.

- PackageUpdatesCheck: Use search repo to find old packages to fix
  checking for OldPackageUpdate results in overlays.

- Make 'NonsolvableDeps' a scannable keyword alias.

- Drop metadata.xml indentation and empty element results from
  warning to style level.

- Drop BadDescription and RedundantLongDescription result levels
  from warning to style.

- Restrict UnknownCategoryDirs result to the gentoo repo.

- Apply target repo base profile masks across all scan profiles
  (#281).

- Drop pickle-based reporter support -- use the scan API call to
  create and access result objects.

- pkgcheck replay: Drop pickle stream support, use JSON support
  instead from the JsonStream reporter.

---------------------------
pkgcheck 0.8.2 (2021-02-09)
---------------------------

- Generate checkrunners per target restriction (#279).

- Fix result object re-creation issues (#276).

---------------------------
pkgcheck 0.8.1 (2021-01-28)
---------------------------

- Include tree-sitter-bash files in dist tarball.

---------------------------
pkgcheck 0.8.0 (2021-01-27)
---------------------------

- Add Style priority level for keywords that's between Warning and Info levels.

- EclassDocMissingVar: Ignore underscore-prefixed vars as it's assumed these are
  internal only.

- pkgcheck scan: Add support for profiles path target restrictions.  Now
  ``pkgcheck scan`` can be pointed at dir and file targets inside the profiles
  directory and relevant checks will be run against them. Note that dir targets
  will run checks against all path descendents.

- pkgcheck scan: Add support for incremental profile scanning. This means all
  profile changes will get run against relevant checks when using ``pkgcheck
  scan --commits``.

- GentooRepoCheck: Allow specifically selected checks to override skip (#261).

- pkgcheck scan: Add support to forcibly disable all pkg filters via passing
  'false', 'no', or 'n'. This provides the ability to disable any filters that
  would otherwise be enabled by default.

- pkgcheck scan: Support checkset and check args for the --exit option.

- Use arches from profiles.desc instead of pulling them from make.defaults
  (#237).

- pkgcheck scan: Enable profile checks when using ``pkgcheck scan --commits``
  if profile changes are detected.

- DependencyCheck: Split outdated blocker checks into OutdatedBlockersCheck
  since required addons are now strictly enforced for cache addons.

- pkgcheck scan: Staged changes are now ignored when using ``pkgcheck scan
  --commits``. Note that due to how ``git stash`` works, they'll be unstaged
  on scan completion.

- NonsolvableDepsInExp: Switch from warning level to error level to match other
  visibility results.

- VirtualKeywordsUpdate: Replace MissingVirtualKeywords with result that flags
  virtuals with keywords that could be added.

- Add basic API for running package scans (#52).

- pkgcheck scan: Drop 'repo' -f/--filter filter type since it's underused and
  doesn't mesh well with the new, granular filtering support.

- BadCommitSummary: Escape regex strings in package names (#256).

- pkgcheck scan: Add support for targeted --filter options that can be enabled
  per keyword, check, or checkset.

- pkgcheck scan: Re-add support for -C/--checksets option that must be defined
  in the CHECKSETS config section. Also, move 'all' and 'net' aliases from
  -c/--checks to virtual checksets.

- MisplacedEclassVar: Add support for flagging misplaced @PRE_INHERIT eclass
  variables in ebuilds.

- Network requests now use streamed GET requests instead of HEAD with fallback
  to avoid various webservers not supporting HEAD requests.

- MissingMove: Properly ignore git ebuild file renames.

- pkgcheck cache: Add initial -r/--repo option support (#251).

- Force using the fork start method for multiprocessing (#254).

- pkgcheck scan: Prefer path restrictions during restriction generation if the
  targets are in the target repo.

- UnusedGlobalUseExpand: Check for unused global USE_EXPAND variables.

- Drop support for python-3.6 and python-3.7.

---------------------------
pkgcheck 0.7.9 (2020-12-05)
---------------------------

- GitCommitsCheck: Fix package vs category level summary checks.

---------------------------
pkgcheck 0.7.8 (2020-12-04)
---------------------------

- pkgcheck show: Add ``-C/--caches`` support.

- BadCommitSummary: Support flagging bad category level commit
  summaries (#250).

- FormatReporter: Raise exception for unhandled integer key args.

- Treat git rename operations as addition and removal for package
  changes (#249).

- PerlCheck is now an optional check that isn't run by default
  since most users won't have the required dependency installed.

- Allow additive -c/--checks args that add checks to the default
  set to run. For example, use ``pkgcheck scan -c=+PerlCheck`` to
  run PerlCheck in addition to the default checks.

- InvalidManifest: Flag ebuilds with invalid Manifest files.

- pkgcheck scan: Support eclass file target restrictions.

- MissingMove: Flag packages on local commits that are renamed with
  no corresponding move package update.

- MissingSlotmove: Flag packages on local commits with changed SLOT
  with no corresponding slotmove package update.

- MaintainerNeeded: Flag packages with invalid maintainer-needed
  comments (#239).

- pkgcheck scan: Display cache update progress by default.

- LiveOnlyPackage: Flag ebuilds that only have VCS-based versions.

- pkgcheck scan: Support a configurable exit status via ``--exit``
  (#28).

- pkgcheck scan: Drop --sorted option that isn't useful enough to
  keep around due to check parallelization.

- MatchingChksums: Ignore go.mod related false positives (#228).

- EclassDocMissingFunc: Flag eclasses missing docs for an exported
  function.

- EclassDocMissingVar: Flag eclasses missing docs for an exported
  variable.

- InternalEclassFunc: Flag ebuilds using internal functions from an
  eclass.

- IndirectInherits: Flag ebuilds using functions from an indirectly
  inherited eclass.

- MissingInherits: Flag ebuilds with missing eclass inherits.

- UnusedInherits: Flag ebuilds with unused eclass inherits.

- PythonCompatUpdate: Flag ebuilds with PYTHON_COMPAT that can be
  updated to support newer python versions.

- Dump all pickled caches atomically (#244).

- UnsupportedEclassEapi: Flag ebuilds that inherit an eclass with
  outdated @SUPPORTED_EAPIS.

- EclassDocError: Flag eclasses that fail eclass doc tag parsing.

- RedundantPackageUpdate: Flag package update entries that have the
  same source and destination.

- ProfileAddon: Only enable exp profiles for explicitly selected
  keywords and not when keywords are selected by default.

- pkgcheck scan: Don't load system/user configs when explicitly
  disabled via ``--config no``.

---------------------------
pkgcheck 0.7.7 (2020-07-05)
---------------------------

- Avoid trying to match old packages against current repo for git support (#215).

- Rename DeprecatedPkg result keyword to DeprecatedDep and try to disambiguate its output
  message (#218).

- FormatReporter: Use an empty string for unmatched variables (#211) and add the result output
  name to the available attributes.

- DroppedKeywordsCheck: Disregard non-VCS pkgs without KEYWORDS (#224).

- Ignore license and keyword settings from system config for StableRequest results (#229).

- pkgcheck scan: Support output name arguments for -k/--keywords (#221).

- StableArchesAddon: Use known stable arches from arches.desc (GLEP 72) if available (#230).

- pkgcheck scan: Fully support custom user config files via --config.

- ProfilesAddon: Automatically enable experimental profiles for selected arches that only have
  experimental profiles (#222) and selected keywords that require them (#225).

- VisibilityCheck: Sort failed package atoms for NonsolvableDep results (#223).

- Filter package atoms from path list when scanning git commits (#217).

- Use a ``git stash`` context manager when scanning commits so untracked files or uncommitted
  changes are ignored.

- Only add eclass directory when scanning git commits if it exists in the target repo (#231).

---------------------------
pkgcheck 0.7.6 (2020-02-09)
---------------------------

- VariableInHomepage: Include parameter expansion chars in flagged variable and
  drop flagging for unbracketed variables until bash parsing support exists.

- Drop PythonSingleUseMismatch result since python-single-r1.eclass will no
  longer generate PYTHON_TARGETS.

- FetchablesUrlCheck: Disable package feed filtering so all defined SRC_URI
  URLs are scanned by default.

- Output create/update git repo cache message to stderr by default to help tell
  the user what's happening during possibly long scan delays.

- Add config file support at /etc/pkgcheck/pkgcheck.conf,
  ~/.config/pkgcheck/pkgcheck.conf, and metadata/pkgcheck.conf for system-wide,
  user, and repo-specific default settings respectively. Any settings found in
  those config files will be overridden by matching command line arguments.
  Almost all command line arguments can be set in config files, see the man
  page or online docs for config examples.

- For network checks, add fallback to GET requests if HEAD requests fail with
  501 or 405 HTTP errors (#208).

---------------------------
pkgcheck 0.7.5 (2020-01-26)
---------------------------

- RedundantLongDescription: Flag redundant longdescription metadata.xml
  elements (#205).

- RedundantDodir: Flag redundant dodir usage (#169).

- pkgcheck scan: Add special argument 'net' for -c/--checks option that enables
  all network checks. This allows for easily running all network checks using
  something similar to ``pkgcheck scan --net -c net``.

- AbsoluteSymlink: Flag dosym calls using paths starting with ${EPREFIX}.

- DeprecatedInsinto: Flag deprecated insinto usage with unnecessary quote usage.

- pkgcheck scan: Show a traceback and forcibly exit on unexpected exceptions
  when running checks.

- EclassBashSyntaxError: Report bash syntax errors in eclasses.

- pkgcheck scan: Allow location specific scopes to override target path
  restrict scope. This makes scanning against a file path target like
  ${REPO_PATH}/eclass only enable eclass checks instead of doing a full repo
  scan.

- pkgcheck scan: Allow path target args of '.' or '..' to work as expected.

- RdependChange: Flag non-live, locally committed packages with altered RDEPEND
  lacking revbumps.

- ``pkgcheck scan --commits`` now enables eclass checks if it notices any
  relevant eclass changes in the local repo.

- EclassHeaderCheck: Add initial eclass header checks similar to the ones done
  against ebuilds in the gentoo repo.

- pkgcheck scan: Drop the -C/--checkset option, it might return in some form
  once reworked config file support is done.

- MetadataUrlCheck: Add initial check for metadata.xml URL validity (#167).

- Ignore unstaged changes when generating targets for ``pkgcheck scan
  --commits``.

- RedundantUriRename: Flag redundant SRC_URI renames (#196).

---------------------------
pkgcheck 0.7.4 (2020-01-11)
---------------------------

- BinaryFile: Ignore some classes of false positives that use multiple
  encodings.

- Output repo and commit related results after any package related results
  found during scanning if using a relevant scan scope level.

- Sort git commit-related results by name or description for multiple results
  against a single commit.

- BadCommitSummary: Convert to commit result instead of package result since it
  directly relates to the commit made more than the package itself.

- Add optional ref argument support for --commits option. This allows passing a
  commit or reference to diff the current tree against in order to determine
  scanning targets.

- GitPkgCommitsCheck: Flag all incorrect copyright dates instead of just
  outdated ones.

- GitCommitsCheck: Use a single ``git cat-file`` process for verifying all
  Fixes/Reverts tags instead of one per commit.

- InvalidCommitMessage: Check for empty lines between summary, body, and tags.

---------------------------
pkgcheck 0.7.3 (2019-12-29)
---------------------------

- Flag git tags and commit messages that don't follow specifications described
  in GLEP 66 (#186) via InvalidCommitTag and InvalidCommitMessage results.

- Skip reporting blocker dependencies marked as deprecated.

---------------------------
pkgcheck 0.7.2 (2019-12-20)
---------------------------

- pkgcheck scan: Change --filtered option to -f/--filter which supports both
  'repo' and 'latest' arguments to filter scanned packages (#184).

- Fix ``pkgcheck scan --commits`` usage with overlays (#188).

- MissingUseDepDefault: Check unconditional use deps for missing defaults,
  previously only conditional flags were being checked.

- DuplicateEclassInherits: Add initial result for flagging duplicate eclass
  inherits.

- BadWhitespaceCharacter: Add initial result for flagging unicode whitespace in
  ebuilds that bash doesn't treat as regular whitespace.

- ProfilesCheck: Add support for validating package.deprecated entries.

- Use .git/info/exclude from repos in addition to .gitignore to ignore files
  for relevant checks.

---------------------------
pkgcheck 0.7.1 (2019-11-30)
---------------------------

- DeprecatedPkg: Add initial result for flagging package dependencies
  deprecated via package.deprecated.

- DeprecatedEclassCheck: Add support for conditionally deprecating eclasses
  with epatch and versionator being the first eclasses to be flagged for
  conditional deprecation.

- SourcingCheck: Add separate check to validate ebuild sourcing and flag
  invalid SLOTs via a new InvalidSlot result.

- pkgcheck scan: Add --sorted option to forcibly perform a global sort -- only
  useful for limited cases such as generating expected test output.

- pkgcheck cache: Add support for listing and removing cache types for
  non-registered repos.

- pkgcheck scan: Replace --git-disable/--profile-cache options with --cache. By
  default all caches are enabled. To disable all of them, use something similar
  to '--cache false'.

  Cache types can also be enabled or disabled individually using a
  comma-separated cache type list, e.g. '--cache profiles' will only enable
  profiles caches and '--cache=-git' will only disable git caches leaving
  all other caches enabled.

- Prioritize checks that scan for metadata errors so they get run before checks
  that use the related metadata attrs.

- Fix memory leak when generating caches for certain git repos (#178).

- pkgcheck scan: Drop --profiles-base option.

- Avoid caching a repo's base package.mask for profile filters in order to
  avoid more cases of profile cache invalidation.

- Split InvalidDependency into individual attr results, e.g. InvalidRdepend.

- Split RestrictsCheck into separate checks for RESTRICT and PROPERTIES.

- AbsoluteSymlinkCheck: Report dosym usage with path variables, e.g. ${ED}.

- BadHomepage: Flag packages using a generic Gentoo HOMEPAGE (#177).

- Add initial support for using a repo's .gitignore file to avoid reporting
  matching files for certain results (#140).

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
