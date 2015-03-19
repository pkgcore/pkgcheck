# Copyright: 2006 Marien Zwart <marienz@gentoo.org>
# License: BSD/GPL2


"""Default checks."""

# Please keep the imports and plugins sorted.
from pkgcheck import (
    cleanup, codingstyle, deprecated, dropped_keywords, feeds, glsa_scan, imlate,
    metadata_checks, metadata_xml, pkgdir_checks, repo_metadata, report_stream,
    reporters, stale_unstable, unstable_only, visibility, whitespace,
)

pkgcore_plugins = {
    'check': [
        cleanup.RedundantVersionReport,
        codingstyle.BadInsIntoCheck,
        deprecated.DeprecatedEAPIReport,
        deprecated.DeprecatedEclassReport,
        dropped_keywords.DroppedKeywordsReport,
        glsa_scan.TreeVulnerabilitiesReport,
        imlate.ImlateReport,
        metadata_checks.LicenseMetadataReport,
        metadata_checks.IUSEMetadataReport,
        metadata_checks.UnusedLocalFlagsReport,
        metadata_checks.DependencyReport,
        metadata_checks.KeywordsReport,
        metadata_checks.SrcUriReport,
        metadata_checks.DescriptionReport,
        metadata_checks.RestrictsReport,
        metadata_xml.PackageMetadataXmlCheck,
        metadata_xml.CategoryMetadataXmlCheck,
        pkgdir_checks.PkgDirReport,
        repo_metadata.UnusedGlobalFlags,
        repo_metadata.UnusedLicense,
        repo_metadata.RequiredChksums,
        stale_unstable.StaleUnstableReport,
        unstable_only.UnstableOnlyReport,
        visibility.VisibilityReport,
        whitespace.WhitespaceCheck,
        ],
    'transform': [
        feeds.VersionToEbuild,
        feeds.EbuildToVersion,
        feeds.VersionToPackage,
        feeds.VersionToCategory,
        feeds.PackageToRepo,
        feeds.CategoryToRepo,
        feeds.PackageToCategory,
        ],
    'reporter': [
        reporters.StrReporter,
        reporters.FancyReporter,
        reporters.XmlReporter,
        reporters.NullReporter,
        report_stream.PickleStream,
        report_stream.BinaryPickleStream,
        ]
    }
