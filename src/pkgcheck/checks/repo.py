import os

from snakeoil.osutils import pjoin

from .. import base
from ..utils import is_binary


class BinaryFile(base.Error):
    """Binary file found in the repository."""

    threshold = base.repository_feed

    def __init__(self, path):
        super().__init__()
        self.path = path

    @property
    def desc(self):
        return f"binary file found in repository: {self.path!r}"


class RepoDirCheck(base.GentooRepoCheck, base.EmptyFeed):
    """Scan all files in the repository for issues."""

    feed_type = base.repository_feed
    scope = base.repository_scope
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
