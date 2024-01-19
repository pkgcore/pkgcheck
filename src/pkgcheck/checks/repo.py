import os
import pathlib

from snakeoil.osutils import pjoin

from .. import addons, base, results, sources
from ..packages import RawCPV
from ..utils import is_binary
from . import GentooRepoCheck, RepoCheck


class BinaryFile(results.Error):
    """Binary file found in the repository."""

    def __init__(self, path):
        super().__init__()
        self.path = path

    @property
    def desc(self):
        return f"binary file found in repository: {self.path!r}"


class RepoDirCheck(GentooRepoCheck, RepoCheck):
    """Scan all files in the repository for issues."""

    _source = (sources.EmptySource, (base.repo_scope,))
    required_addons = (addons.git.GitAddon,)
    known_results = frozenset([BinaryFile])

    # repo root level directories that are ignored
    ignored_root_dirs = frozenset([".git"])

    def __init__(self, *args, git_addon):
        super().__init__(*args)
        self.gitignored = git_addon.gitignored
        self.repo = self.options.target_repo
        self.ignored_paths = {pjoin(self.repo.location, x) for x in self.ignored_root_dirs}
        self.dirs = [self.repo.location]

    def finish(self):
        while self.dirs:
            for entry in os.scandir(self.dirs.pop()):
                if entry.is_dir(follow_symlinks=False):
                    if entry.path in self.ignored_paths or self.gitignored(entry.path):
                        continue
                    self.dirs.append(entry.path)
                elif is_binary(entry.path):
                    if not self.gitignored(entry.path):
                        rel_path = entry.path[len(self.repo.location) + 1 :]
                        yield BinaryFile(rel_path)


class EmptyCategoryDir(results.CategoryResult, results.Error):
    """Empty category directory in the repository."""

    scope = base.repo_scope

    @property
    def desc(self):
        return f"empty category directory: {self.category}"


class EmptyPackageDir(results.PackageResult, results.Error):
    """Empty package directory in the repository."""

    scope = base.repo_scope

    @property
    def desc(self):
        return f"empty package directory: {self.category}/{self.package}"


class EmptyDirsCheck(GentooRepoCheck, RepoCheck):
    """Scan for empty category or package directories."""

    _source = (sources.EmptySource, (base.repo_scope,))
    known_results = frozenset({EmptyCategoryDir, EmptyPackageDir})

    def __init__(self, *args):
        super().__init__(*args)
        self.repo = self.options.target_repo

    def finish(self):
        repo_p = pathlib.Path(self.repo.location)
        for cat, pkgs in sorted(self.repo.packages.items()):
            # ignore entries in profiles/categories with nonexistent dirs
            if not pkgs:
                if (repo_p / cat).exists():
                    yield EmptyCategoryDir(pkg=RawCPV(cat, None, None))
                continue
            for pkg in sorted(pkgs):
                if not self.repo.versions[(cat, pkg)]:
                    yield EmptyPackageDir(pkg=RawCPV(cat, pkg, None))


class CategoryIsNotDirectory(results.CategoryResult, results.Error):
    """A category was found that exists but isn't a directory."""

    scope = base.repo_scope

    @property
    def desc(self):
        return f"category on disk exists and is not a directory: {self.category}"


class RepositoryCategories(RepoCheck):
    """Scan for fundamental category issues in the repository layout"""

    _source = (sources.EmptySource, (base.repo_scope,))
    known_results = frozenset({CategoryIsNotDirectory})

    def finish(self):
        repo = self.options.target_repo
        repo_p = pathlib.Path(repo.location)
        for category in repo.categories:
            p = repo_p / category
            if p.exists() and not p.is_dir():
                yield CategoryIsNotDirectory(pkg=RawCPV(category, None, None))
