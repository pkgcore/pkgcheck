from multiprocessing import cpu_count, Queue, Process
from multiprocessing.pool import Pool
import os

from snakeoil.osutils import pjoin

from .. import base
from ..utils import is_binary


class BinaryFile(base.Error):
    """Binary file found in the repository."""

    __slots__ = ("path",)

    threshold = base.repository_feed

    def __init__(self, path):
        super().__init__()
        self.path = path

    @property
    def short_desc(self):
        return f"binary file found in repository: {self.path!r}"


class IteratorQueue(object):
    """Iterator based on an output queue fed by a thread/process pool."""

    def __init__(self, queue, inserter, pool, sentinel=None, processes=None):
        self.queue = queue
        self.inserter = inserter
        self.pool = pool
        self.sentinel = sentinel
        self.processes = processes if processes is not None else cpu_count()

    def __iter__(self):
        return self

    def __next__(self):
        result = self.queue.get()
        if result is self.sentinel:
            self.processes -= 1
            if self.processes == 0:
                self.inserter.join()
                self.pool.join()
                raise StopIteration
            return self.__next__()
        return result


class RepoDirCheck(base.DefaultRepoCheck):
    """Scan all files in the repository for issues."""

    feed_type = base.repository_feed
    scope = base.repository_scope
    known_results = (BinaryFile,)

    ignored_dirs = frozenset(['.git'])

    def __init__(self, options):
        super().__init__(options)
        self.repo = options.target_repo

    def feed(self, pkg):
        pass

    def _scan_file(self, paths, results, sentinel=None):
        while True:
            path = paths.get()
            if path is sentinel:
                results.put(sentinel)
                return
            elif is_binary(path):
                results.put(BinaryFile(path[len(self.repo.location) + 1:]))

    def _insert_files(self, queue, processes, sentinel=None):
        for root, dirs, files in os.walk(self.repo.location):
            for d in self.ignored_dirs.intersection(dirs):
                dirs.remove(d)
            for f in files:
                queue.put(pjoin(root, f))
        for i in range(processes):
            queue.put(sentinel)

    def finish(self):
        path_queue = Queue()
        results_queue = Queue()
        processes = cpu_count()
        # producer walks the repo directory, queuing file paths to check
        p = Process(target=self._insert_files, args=(path_queue, processes))
        p.start()
        # consumers pull paths from the queue, perform binary checks, and queue
        # reports on a positive results
        pool = Pool(processes, self._scan_file, (path_queue, results_queue))
        pool.close()
        return IteratorQueue(results_queue, p, pool, processes=processes)
