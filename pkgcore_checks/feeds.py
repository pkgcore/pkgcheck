# Copyright: 2006 Marien Zwart <marienz@gentoo.org>
# License: GPL2


"""Feed classes: pass groups of packages to other addons."""


import operator
import itertools

from pkgcore_checks import base

from pkgcore.restrictions import util
from pkgcore.util.compatibility import any


class VersionToEbuild(base.Addon):

    """Convert from just a package to a (package, list_of_lines) tuple."""

    transforms = {
        base.versioned_feed: (base.ebuild_feed, base.version_scope, 20)}

    def transform(self, feed):
        for pkg in feed:
            yield pkg, list(pkg.ebuild.get_fileobj())


class EbuildToVersion(base.Addon):

    """Convert (package, list_of_lines) to just package."""

    transforms = {
        base.ebuild_feed: (base.versioned_feed, base.version_scope, 5)}

    def transform(self, feed):
        for pkg, lines in feed:
            yield pkg


class VersionToPackage(base.Addon):

    transforms = {
        base.versioned_feed: (base.package_feed, base.package_scope, 10)}

    def transform(self, versions):
        for package, pkg_vers in itertools.groupby(versions,
                                                   operator.attrgetter('key')):
            # groupby returns an iterator.
            yield tuple(pkg_vers)


class PackageToCategory(base.Addon):

    transforms = {
        base.package_feed: (base.category_feed, base.category_scope, 10)}

    @staticmethod
    def _filter(packages):
        return packages[0].category

    def transform(self, packages):
        for cat, cat_pkgs in itertools.groupby(packages, self._filter):
            chunk = []
            for subchunk in cat_pkgs:
                chunk.extend(subchunk)
            yield tuple(chunk)


class PackageOrCategoryToRepo(base.Addon):

    transforms = {
        base.package_feed: (base.repository_feed, base.repository_scope, 10),
        base.category_feed: (base.repository_feed, base.repository_scope, 10),
        }

    def transform(self, input):
        all_packages = []
        for packages in input:
            all_packages.extend(packages)
        yield packages


class RestrictedRepoSource(object):

    feed_type = base.versioned_feed
    cost = 10

    def __init__(self, repo, limiter):
        self.repo = repo
        self.limiter = limiter
        for scope, attrs in [
            (base.version_scope, ['fullver', 'version', 'rev']),
            (base.package_scope, ['package']),
            (base.category_scope, ['category']),
            ]:
            if any(util.collect_package_restrictions(limiter, attrs)):
                self.scope = scope
                return
        self.scope = base.repository_scope

    def feed(self):
        return self.repo.itermatch(self.limiter, sorter=sorted)
