# Copyright: 2006 Marien Zwart <marienz@gentoo.org>
# License: BSD/GPL2

"""Default checks."""

# Please keep the imports and plugins sorted.
from pkgcheck import (
    cleanup, codingstyle, deprecated, dropped_keywords, feeds, glsa_scan,
    imlate, metadata_checks, metadata_xml, pkgdir_checks, repo_metadata,
    reporters, stale_unstable, unstable_only, visibility, whitespace,
)
from pkgcheck.scripts import pkgcheck_replay_stream

pkgcore_plugins = {
    'check': [
        cleanup.RedundantVersionReport,
        codingstyle.BadInsIntoCheck,
        deprecated.DeprecatedEAPIReport,
        deprecated.DeprecatedEclassReport,
        dropped_keywords.DroppedKeywordsReport,
        glsa_scan.TreeVulnerabilitiesReport,
        imlate.ImlateReport,
        metadata_checks.DependencyReport,
        metadata_checks.DescriptionReport,
        metadata_checks.IUSEMetadataReport,
        metadata_checks.KeywordsReport,
        metadata_checks.LicenseMetadataReport,
        metadata_checks.MissingSlotDepReport,
        metadata_checks.RestrictsReport,
        metadata_checks.SrcUriReport,
        metadata_checks.UnusedLocalFlagsReport,
        metadata_xml.CategoryMetadataXmlCheck,
        metadata_xml.PackageMetadataXmlCheck,
        pkgdir_checks.PkgDirReport,
        repo_metadata.ManifestReport,
        repo_metadata.UnusedGlobalFlags,
        repo_metadata.UnusedLicense,
        repo_metadata.RepoProfilesReport,
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
        pkgcheck_replay_stream.BinaryPickleStream,
        pkgcheck_replay_stream.PickleStream,
        reporters.FancyReporter,
        reporters.NullReporter,
        reporters.StrReporter,
        reporters.XmlReporter,
        ]
    }
