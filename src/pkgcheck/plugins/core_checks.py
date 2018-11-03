"""Default checks."""

# Please keep the imports and plugins sorted.
from .. import feeds, reporters
from ..checks import (
    cleanup, codingstyle, deprecated, dropped_keywords, glsa,
    imlate, metadata_checks, metadata_xml, pkgdir_checks, repo_metadata,
    stale_unstable, unstable_only, visibility, whitespace,
)

pkgcore_plugins = {
    'check': [
        cleanup.RedundantVersionReport,
        codingstyle.AbsoluteSymlinkCheck,
        codingstyle.BadInsIntoCheck,
        codingstyle.HttpsAvailableCheck,
        codingstyle.PathVariablesCheck,
        codingstyle.PortageInternalsCheck,
        deprecated.DeprecatedEclassReport,
        dropped_keywords.DroppedKeywordsReport,
        glsa.TreeVulnerabilitiesReport,
        imlate.ImlateReport,
        metadata_checks.DependencyReport,
        metadata_checks.DescriptionReport,
        metadata_checks.IUSEMetadataReport,
        metadata_checks.RequiredUSEMetadataReport,
        metadata_checks.KeywordsReport,
        metadata_checks.LicenseMetadataReport,
        metadata_checks.LocalUSECheck,
        metadata_checks.MissingSlotDepReport,
        metadata_checks.PkgEAPIReport,
        metadata_checks.RestrictsReport,
        metadata_checks.SrcUriReport,
        metadata_xml.CategoryMetadataXmlCheck,
        metadata_xml.PackageMetadataXmlCheck,
        pkgdir_checks.PkgDirReport,
        repo_metadata.GlobalUSECheck,
        repo_metadata.LicenseGroupsCheck,
        repo_metadata.ManifestReport,
        repo_metadata.PackageUpdatesCheck,
        repo_metadata.ProfilesCheck,
        repo_metadata.RepoProfilesReport,
        repo_metadata.UnusedEclassesCheck,
        repo_metadata.UnusedLicensesCheck,
        repo_metadata.UnusedMirrorsCheck,
        stale_unstable.StaleUnstableReport,
        unstable_only.UnstableOnlyReport,
        visibility.VisibilityReport,
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
