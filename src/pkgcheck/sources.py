"""Custom package sources used for feeding addons."""

from pkgcore.ebuild import cpv, restricts
from pkgcore.restrictions import packages

from . import addons, base


class RawRepoSource(base.GenericSource):
    """Ebuild repository source returning raw CPV objects."""

    feed_type = base.raw_versioned_feed

    def __init__(self, options, limiter):
        super().__init__(options, limiter)
        # Drop repo restriction if one exists as we're matching against a faked
        # repo with a different repo_id.
        try:
            if isinstance(self.limiter[0], restricts.RepositoryDep):
                self.limiter = packages.AndRestriction(*self.limiter[1:])
        except TypeError:
            pass

    def __iter__(self):
        yield from self.repo.itermatch(
            self.limiter, sorter=sorted, raw_pkg_cls=lambda *args: base.RawCPV(*args))


class RestrictionRepoSource(base.GenericSource):
    """Ebuild repository source supporting custom restrictions."""

    def __init__(self, restriction, *args):
        super().__init__(*args)
        self.limiter = packages.AndRestriction(*(self.limiter, restriction))


class FilteredRepoSource(base.GenericSource):
    """Repository source that uses profiles/package.mask to filter packages."""

    def __init__(self, *args):
        super().__init__(*args)
        self.repo = self.options.domain.filter_repo(
            self.repo, pkg_masks=(), pkg_unmasks=(),
            pkg_accept_keywords=(), pkg_keywords=(), profile=False)


class GitCommitsRepoSource(base.GenericSource):
    """Repository source for locally changed packages in git history.

    Parses local git log history to determine packages with changes that
    haven't been pushed upstream yet.
    """

    required_addons = (addons.GitAddon,)

    def __init__(self, options, git_addon, limiter):
        super().__init__(options, limiter)
        self.repo = git_addon.commits_repo(addons.GitChangedRepo)

        # Drop repo restriction if one exists as we're matching against a faked
        # repo with a different repo_id.
        try:
            repo_limiter = self.limiter[0]
        except TypeError:
            repo_limiter = None
        if isinstance(repo_limiter, restricts.RepositoryDep):
            self.limiter = packages.AndRestriction(*self.limiter[1:])
