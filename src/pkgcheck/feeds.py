"""Feed classes: pass groups of packages to other addons."""

from operator import attrgetter
import sys

from pkgcore.ebuild import restricts
from pkgcore.restrictions import packages, util
from snakeoil.demandload import demandload

from . import addons, base

demandload('inspect')


class VersionToEbuild(base.Transform):
    """Convert from just a package to a (package, list_of_lines) tuple."""

    source = base.versioned_feed
    dest = base.ebuild_feed
    scope = base.version_scope
    cost = 20

    def feed(self, pkg, reporter):
        self.child.feed((pkg, tuple(pkg.ebuild.text_fileobj())), reporter)


class EbuildToVersion(base.Transform):
    """Convert (package, list_of_lines) to just package."""

    source = base.ebuild_feed
    dest = base.versioned_feed
    scope = base.version_scope
    cost = 5

    def feed(self, pair, reporter):
        self.child.feed(pair[0], reporter)


class _Collapse(base.Transform):
    """Collapse the input into tuples with a function returning the same val.

    Override keyfunc in a subclass and set the C{transforms} attribute.
    """

    def start(self, reporter):
        base.Transform.start(self, reporter)
        self.chunk = None
        self.key = None

    def keyfunc(self, pkg):
        raise NotImplementedError(self.keyfunc)

    def feed(self, pkg, reporter):
        key = self.keyfunc(pkg)
        if key == self.key:
            # New version for our current package.
            self.chunk.append(pkg)
        else:
            # Package change.
            if self.chunk is not None:
                self.child.feed(tuple(self.chunk), reporter)
            self.chunk = [pkg]
            self.key = key

    def finish(self, reporter):
        # Deal with empty runs.
        if self.chunk is not None:
            self.child.feed(tuple(self.chunk), reporter)
        base.Transform.finish(self, reporter)
        self.chunk = None
        self.key = None


class VersionToPackage(_Collapse):

    source = base.versioned_feed
    dest = base.package_feed
    scope = base.package_scope
    cost = 10

    keyfunc = attrgetter('key')


class VersionToCategory(_Collapse):

    source = base.versioned_feed
    dest = base.category_feed
    scope = base.category_scope
    cost = 10

    keyfunc = attrgetter('category')


class _PackageOrCategoryToRepo(base.Transform):

    def start(self, reporter):
        base.Transform.start(self, reporter)
        self.repo = []

    def feed(self, item, reporter):
        self.repo.append(item)

    def finish(self, reporter):
        self.child.feed(self.repo, reporter)
        base.Transform.finish(self, reporter)
        self.repo = None


class PackageToRepo(_PackageOrCategoryToRepo):

    source = base.package_feed
    dest = base.repository_feed
    scope = base.repository_scope
    cost = 10


class CategoryToRepo(_PackageOrCategoryToRepo):

    source = base.category_feed
    dest = base.repository_feed
    scope = base.repository_scope
    cost = 10


class PackageToCategory(base.Transform):

    source = base.package_feed
    dest = base.category_feed
    scope = base.category_scope
    cost = 10

    def start(self, reporter):
        base.Transform.start(self, reporter)
        self.chunk = None
        self.category = None

    def feed(self, item, reporter):
        category = item[0].category
        if category == self.category:
            self.chunk.extend(item)
        else:
            if self.chunk is not None:
                self.child.feed(tuple(self.chunk), reporter)
            self.chunk = list(item)
            self.category = category

    def finish(self, reporter):
        if self.chunk is not None:
            self.child.feed(tuple(self.chunk), reporter)
        base.Transform.finish(self, reporter)
        self.category = None
        self.chunk = None


class RestrictedRepoSource(base.GenericSource):
    """Generic ebuild repository source."""

    def __init__(self, *args):
        super().__init__(*args)
        for scope, attrs in ((base.version_scope, ['fullver', 'version', 'rev']),
                             (base.package_scope, ['package']),
                             (base.category_scope, ['category'])):
            if any(util.collect_package_restrictions(self.limiter, attrs)):
                self.scope = scope
                return
        self.scope = base.repository_scope

    def feed(self):
        return self.repo.itermatch(self.limiter, sorter=sorted)


class FilteredRepoSource(RestrictedRepoSource):
    """Repository source that uses profiles/package.mask to filter packages."""

    filter_type = base.mask_filter

    def __init__(self, *args):
        super().__init__(*args)
        self.repo = self.options.domain.filter_repo(
            self.repo, pkg_masks=(), pkg_unmasks=(),
            pkg_accept_keywords=(), pkg_keywords=(), profile=False)


class GitCommitsRepoSource(RestrictedRepoSource):
    """Repository source for locally changed packages in git history.

    Parses local git log history to determine packages with changes that
    haven't been pushed upstream yet.
    """

    required_addons = (addons.GitAddon,)
    filter_type = base.git_filter

    def __init__(self, options, git_addon, limiter):
        super().__init__(options, limiter)
        self.repo = git_addon.commits_repo(addons.GitChangesRepo)

        # Drop repo restriction if one exists as we're matching against a faked
        # repo with a different repo_id.
        try:
            repo_limiter = self.limiter[0]
        except TypeError:
            repo_limiter = None
        if isinstance(repo_limiter, restricts.RepositoryDep):
            self.limiter = packages.AndRestriction(*self.limiter[1:])


def all_sources():
    """Iterator that yields all defined source classes."""
    for name, cls in inspect.getmembers(sys.modules[__name__]):
        if inspect.isclass(cls) and issubclass(cls, base.GenericSource):
            yield cls
