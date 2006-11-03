# Copyright: 2006 Marien Zwart <marienz@gentoo.org>
# License: GPL2


"""Feed classes: pass groups of packages to other addons."""


import operator
import itertools

from pkgcore_checks import base

from pkgcore.restrictions import packages


class VersionToPackage(base.Addon):

    transforms = [(base.versioned_feed, base.package_feed, 10)]

    def transform(self, versions):
        got_one = False
        for package, pkg_vers in itertools.groupby(versions,
                                                   operator.attrgetter('key')):
            # groupby returns an iterator.
            pkg_vers = tuple(pkg_vers)
            if not got_one:
                # The first one is special. We need to check if we got
                # the entire package. If we do we will assume that our
                # other packages are complete too.

                # This is obviously not optimal but we only hit it for
                # scanning exactly one package, which should be "fast
                # enough" anyway.
                if len(pkg_vers) != len(self.options.target_repo.match(
                        pkg_vers[0].unversioned_atom)):
                    # Not the full package. Bail.
                    return
                got_one = True
            yield pkg_vers


class PackageToCategory(base.Addon):

    transforms = [(base.package_feed, base.category_feed, 10)]

    @staticmethod
    def _filter(packages):
        return packages[0].category

    def transform(self, packages):
        got_one = False
        for cat, cat_pkgs in itertools.groupby(packages, self._filter):
            chunk = []
            for subchunk in cat_pkgs:
                chunk.extend(subchunk)
            cat_pkgs = tuple(chunk)
            if not got_one:
                # Check if we got the entire category.
                # Not very efficient, but only runs for a single category.
                if len(set(package.key for package in cat_pkgs)) != len(
                    self.options.target_repo.packages[cat]):
                    # Not the full category. Bail.
                    return
                got_one = True
            yield cat_pkgs


class PackageOrCategoryToRepo(base.Addon):

    transforms = [
        (base.package_feed, base.repository_feed, 10),
        (base.category_feed, base.repository_feed, 10),
        ]

    @staticmethod
    def _filter(packages):
        return packages[0].category

    def transform(self, chunks):
        packages = []
        cats = set()
        for cat, cat_pkgs in itertools.groupby(chunks, self._filter):
            for subchunk in cat_pkgs:
                packages.extend(subchunk)
            cats.add(cat)
        # Figure out if we saw the entire repo.
        if len(self.options.target_repo.categories) == len(cats):
            yield repo


class RestrictedRepoSource(object):

    feed_type = base.versioned_feed
    cost = 10

    def __init__(self, repo, limiter):
        self.repo = repo
        self.limiter = limiter

    def feed(self):
        return self.repo.itermatch(self.limiter, sorter=sorted)
