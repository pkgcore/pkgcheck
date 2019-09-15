"""Custom package sources used for feeding addons."""

from pkgcore.ebuild.repository import UnconfiguredTree
from pkgcore.restrictions import packages
from snakeoil.osutils import listdir_files, pjoin

from . import addons, base


class _RawRepo(UnconfiguredTree):
    """Repository that allows matching against mismatched/invalid package names."""

    def __init__(self, repo):
        super().__init__(repo.location)

    def _get_versions(self, catpkg):
        """Pass through all packages that end with ".ebuild" extension.

        Deviates from parent in that no package name check is done.
        """
        cppath = pjoin(self.base, catpkg[0], catpkg[1])
        pkg = f'{catpkg[-1]}-'
        lp = len(pkg)
        extension = self.extension
        ext_len = -len(extension)
        try:
            return tuple(
                x[lp:ext_len] for x in listdir_files(cppath)
                if x[ext_len:] == extension)
        except EnvironmentError as e:
            path = pjoin(self.base, os.sep.join(catpkg))
            raise KeyError(f'failed fetching versions for package {path}: {e}') from e


class RawRepoSource(base.GenericSource):
    """Ebuild repository source returning raw CPV objects."""

    feed_type = base.raw_versioned_feed

    def __init__(self, *args):
        super().__init__(*args)
        self.repo = _RawRepo(self.repo)

    def itermatch(self, restrict):
        yield from super().itermatch(restrict, raw_pkg_cls=base.RawCPV)


class RestrictionRepoSource(base.GenericSource):
    """Ebuild repository source supporting custom restrictions."""

    def __init__(self, restriction, *args):
        super().__init__(*args)
        self.restriction = restriction

    def itermatch(self, restrict):
        restrict = packages.AndRestriction(*(restrict, self.restriction))
        yield from super().itermatch(restrict)


class FilteredRepoSource(base.GenericSource):
    """Repository source that uses profiles/package.mask to filter packages."""

    def __init__(self, *args):
        super().__init__(*args)
        self.repo = self.options.domain.filter_repo(
            self.repo, pkg_masks=(), pkg_unmasks=(),
            pkg_accept_keywords=(), pkg_keywords=(), profile=False)


class GitCommitsRepoSource(base.GenericSource):
    """Repository source for locally changed packages in git history.

    Parses git log history to determine packages with changes that
    haven't been pushed upstream yet.
    """

    required_addons = (addons.GitAddon,)

    def __init__(self, options, git_addon):
        super().__init__(options)
        self.repo = git_addon.commits_repo(addons.GitChangedRepo)


class GitCommitsSource(base.GenericSource):
    """Source for local commits in git history.

    Parses git log history to determine commits that haven't been pushed
    upstream yet.
    """

    required_addons = (addons.GitAddon,)

    def __init__(self, options, git_addon):
        super().__init__(options)
        self.commits = git_addon.commits()

    def __iter__(self):
        yield from self.commits
