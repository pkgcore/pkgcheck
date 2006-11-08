# Copyright: 2006 Marien Zwart <marienz@gentoo.org>
# License: GPL2


"""Feed classes: pass groups of packages to other addons."""


import operator
import itertools

from pkgcore_checks import base
from pkgcore.restrictions import util


class VersionToPackage(base.Addon):

    transforms = [
        (base.versioned_feed, base.package_feed, base.package_scope, 10)]

    def transform(self, versions):
        for package, pkg_vers in itertools.groupby(versions,
                                                   operator.attrgetter('key')):
            # groupby returns an iterator.
            yield tuple(pkg_vers)


class PackageToCategory(base.Addon):

    transforms = [
        (base.package_feed, base.category_feed, base.category_scope, 10)]

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

    transforms = [
        (base.package_feed, base.repository_feed, base.repository_scope, 10),
        (base.category_feed, base.repository_feed, base.repository_scope, 10),
        ]

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
            for attr in attrs:
                if any(util.collect_package_restrictions(limiter, attr)):
                    self.scope = scope
                    return
        self.scope = base.repository_scope

    def feed(self):
        return self.repo.itermatch(self.limiter, sorter=sorted)
