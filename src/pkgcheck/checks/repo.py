import os

from snakeoil.osutils import pjoin

from .. import base, results, sources
from ..packages import RawCPV
from ..utils import is_binary
from . import GentooRepoCheck


class BinaryFile(results.Error):
    """Binary file found in the repository."""

    def __init__(self, path):
        super().__init__()
        self.path = path

    @property
    def desc(self):
        return f"binary file found in repository: {self.path!r}"


class RepoDirCheck(GentooRepoCheck):
    """Scan all files in the repository for issues."""

    scope = base.repository_scope
    _source = sources.EmptySource
    known_results = frozenset([BinaryFile])

    # repo root level directories that are ignored
    ignored_root_dirs = frozenset(['.git'])

    def __init__(self, *args):
        super().__init__(*args)
        self.repo = self.options.target_repo
        self.ignored_paths = {
            pjoin(self.repo.location, x) for x in self.ignored_root_dirs}
        self.dirs = [self.repo.location]

    def finish(self):
        while self.dirs:
            for entry in os.scandir(self.dirs.pop()):
                if entry.is_dir(follow_symlinks=False):
                    if entry.path not in self.ignored_paths:
                        self.dirs.append(entry.path)
                elif is_binary(entry.path):
                    yield BinaryFile(entry.path[len(self.repo.location) + 1:])


class EmptyCategoryDir(results.CategoryResult, results.Warning):
    """Empty category directory in the repository."""

    scope = base.repository_scope

    @property
    def desc(self):
        return f'empty category directory: {self.category}'


class EmptyPackageDir(results.PackageResult, results.Warning):
    """Empty package directory in the repository."""

    scope = base.repository_scope

    @property
    def desc(self):
        return f'empty package directory: {self.category}/{self.package}'


class EmptyDirsCheck(GentooRepoCheck):
    """Scan for empty category or package directories."""

    scope = base.repository_scope
    _source = sources.EmptySource
    known_results = frozenset([EmptyCategoryDir, EmptyPackageDir])

    def __init__(self, *args):
        super().__init__(*args)
        self.repo = self.options.target_repo

    def finish(self):
        for cat, pkgs in sorted(self.repo.packages.items()):
            if not pkgs:
                yield EmptyCategoryDir(pkg=RawCPV(cat, None, None))
                continue
            for pkg in sorted(pkgs):
                versions = self.repo.versions[(cat, pkg)]
                if not versions:
                    yield EmptyPackageDir(pkg=RawCPV(cat, pkg, None))
