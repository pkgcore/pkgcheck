"""Default checks."""

# Please keep the imports and plugins sorted.
from .. import feeds, reporters
from ..checks import (
    acct, cleanup, codingstyle, deprecated, dropped_keywords, git, glsa,
    imlate, metadata, metadata_xml, overlays, pkgdir, python,
    profiles, repo, repo_metadata, stablereq, unstable_only, visibility,
    whitespace,
)

pkgcore_plugins = {
    'check': [
        acct.AcctCheck,
        cleanup.RedundantVersionCheck,
        codingstyle.AbsoluteSymlinkCheck,
        codingstyle.BadInsIntoCheck,
        codingstyle.HttpsAvailableCheck,
        codingstyle.ObsoleteUriCheck,
        codingstyle.PathVariablesCheck,
        codingstyle.PortageInternalsCheck,
        deprecated.DeprecatedEclassCheck,
        dropped_keywords.DroppedKeywordsCheck,
        git.GitCommitsCheck,
        glsa.TreeVulnerabilitiesCheck,
        imlate.ImlateCheck,
        metadata.DependencyCheck,
        metadata.DescriptionCheck,
        metadata.HomepageCheck,
        metadata.IUSEMetadataCheck,
        metadata.RequiredUSEMetadataCheck,
        metadata.KeywordsCheck,
        metadata.LicenseMetadataCheck,
        metadata.LocalUSECheck,
        metadata.MetadataCheck,
        metadata.MissingSlotDepCheck,
        metadata.MissingUnpackerDepCheck,
        metadata.RestrictsCheck,
        metadata.SrcUriCheck,
        metadata_xml.CategoryMetadataXmlCheck,
        metadata_xml.PackageMetadataXmlCheck,
        overlays.UnusedInMastersCheck,
        pkgdir.PkgDirCheck,
        profiles.ProfilesCheck,
        profiles.RepoProfilesCheck,
        python.PythonCheck,
        repo.RepoDirCheck,
        repo_metadata.GlobalUSECheck,
        repo_metadata.LicenseGroupsCheck,
        repo_metadata.ManifestConflictCheck,
        repo_metadata.ManifestCheck,
        repo_metadata.PackageUpdatesCheck,
        repo_metadata.UnusedEclassesCheck,
        repo_metadata.UnusedLicensesCheck,
        repo_metadata.UnusedMirrorsCheck,
        stablereq.StableRequestCheck,
        unstable_only.UnstableOnlyCheck,
        visibility.VisibilityCheck,
        whitespace.WhitespaceCheck,
        ],
    'transform': [
        feeds.CategoryToRepo,
        feeds.EbuildToVersion,
        feeds.PackageToCategory,
        feeds.PackageToRepo,
        feeds.VersionToCategory,
        feeds.VersionToEbuild,
        feeds.VersionToPackage,
        ],
    'reporter': [
        reporters.BinaryPickleStream,
        reporters.PickleStream,
        reporters.FancyReporter,
        reporters.NullReporter,
        reporters.StrReporter,
        reporters.JsonReporter,
        reporters.XmlReporter,
        ]
    }
