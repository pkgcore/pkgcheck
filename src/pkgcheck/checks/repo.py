import os

from snakeoil.osutils import pjoin

from .. import base, sources
from ..utils import is_binary
from . import GentooRepoCheck


class BinaryFile(base.Error):
    """Binary file found in the repository."""

    threshold = base.repository_feed

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
    known_results = (BinaryFile,)

    # repo root level directories that are ignored
    ignored_root_dirs = frozenset(['.git'])

    def __init__(self, options):
        super().__init__(options)
        self.repo = options.target_repo
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


class EmptyCategoryDir(base.CategoryResult, base.Warning):
    """Empty category directory in the repository."""

    threshold = base.repository_feed

    @property
    def desc(self):
        return f'empty category directory: {self.category}'


class EmptyPackageDir(base.PackageResult, base.Warning):
    """Empty package directory in the repository."""

    threshold = base.repository_feed

    @property
    def desc(self):
        return f'empty package directory: {self.category}/{self.package}'


class EmptyDirsCheck(GentooRepoCheck):
    """Scan for empty category or package directories."""

    scope = base.repository_scope
    _source = sources.EmptySource
    known_results = (EmptyCategoryDir, EmptyPackageDir)

    def __init__(self, options):
        super().__init__(options)
        self.repo = options.target_repo

    def finish(self):
        for cat, pkgs in sorted(self.repo.packages.items()):
            if not pkgs:
                yield EmptyCategoryDir(pkg=base.RawCPV(cat, None, None))
                continue
            for pkg in sorted(pkgs):
                versions = self.repo.versions[(cat, pkg)]
                if not versions:
                    yield EmptyPackageDir(pkg=base.RawCPV(cat, pkg, None))
