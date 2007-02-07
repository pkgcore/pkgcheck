# Copyright: 2006 Marien Zwart <marienz@gentoo.org>
# License: GPL2


"""Default checks."""

# Please keep the imports and plugins sorted.
from pkgcore_checks import (
    cleanup, deprecated, dropped_keywords, glsa_scan, imlate, metadata_checks,
    metadata_xml, pkgdir_checks, repo_metadata, stale_unstable, unported_mod_x,
    unstable_only, visibility, whitespace, feeds, reporters, report_stream)


pkgcore_plugins = {
    'check': [
        cleanup.RedundantVersionReport,
        deprecated.DeprecatedEclassReport,
        dropped_keywords.DroppedKeywordsReport,
        glsa_scan.TreeVulnerabilitiesReport,
        imlate.ImlateReport,
        metadata_checks.LicenseMetadataReport,
        metadata_checks.IUSEMetadataReport,
        metadata_checks.DependencyReport,
        metadata_checks.KeywordsReport,
        metadata_checks.SrcUriReport,
        metadata_checks.DescriptionReport,
        metadata_checks.RestrictsReport,
        metadata_xml.PackageMetadataXmlCheck,
        metadata_xml.CategoryMetadataXmlCheck,
        pkgdir_checks.PkgDirReport,
        repo_metadata.UnusedLocalFlags,
        repo_metadata.UnusedGlobalFlags,
        repo_metadata.UnusedLicense,
        repo_metadata.ConflictingDigests,
        repo_metadata.ConflictManifestDigest,
        stale_unstable.StaleUnstableReport,
        unported_mod_x.ModularXPortingReport,
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
        report_stream.PickleStream,
        report_stream.BinaryPickleStream,
        ]
    }
