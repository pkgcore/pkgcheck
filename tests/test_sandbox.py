import os
import socket
import tempfile
from functools import partial

import pytest
from pkgcore import landlock
from pkgcore.exceptions import PkgcoreUserException
from snakeoil.cli.arghparse import Namespace
from snakeoil.contexts import GitStash

from pkgcheck import sandbox
from pkgcheck.base import PkgcheckUserException


def options(tmp_path, **kwargs):
    """Build the minimal namespace :py:func:`sandbox.confine` reads."""
    repo = Namespace(location=str(tmp_path / "repo"), trees=(), cache=())
    repo.trees = (repo,)
    defaults = {
        "sandbox": None,
        "net": None,
        "cache_dir": str(tmp_path / "cache"),
        "contexts": [],
        "target_repo": repo,
    }
    return Namespace(**(defaults | kwargs))


def run_confined(confine, options, func):
    """Run *func* in a forked child confined by *options*.

    Confinement can't be undone, so it never touches the test session itself.
    Returns the child's stringified result, or its error.
    """
    read_fd, write_fd = os.pipe()
    if (pid := os.fork()) == 0:  # pragma: no cover
        os.close(read_fd)
        try:
            confine(options)
            os.write(write_fd, str(func()).encode())
        except BaseException as e:
            os.write(write_fd, f"error: {e!r}".encode())
        finally:
            os.close(write_fd)
            os._exit(0)
    os.close(write_fd)
    with os.fdopen(read_fd) as f:
        output = f.read()
    os.waitpid(pid, 0)
    return output


def write_denied(path):
    """Whether the kernel refuses to create a file under *path*."""
    try:
        with open(os.path.join(path, "probe"), "w") as f:
            f.write("data")
    except PermissionError:
        return True
    return False


def tcp_denied():
    """Whether the kernel refuses an outgoing TCP connection.

    Landlock rejects the connect before any packet leaves, so the discard port
    needs nothing listening on it.
    """
    with socket.socket() as s:
        try:
            s.connect(("127.0.0.1", 9))
        except PermissionError:
            return True
        except OSError:
            return False
    return False


class stash(GitStash):
    """A GitStash with a canned verdict, so no real git repo is needed."""

    def __init__(self, path, *, pending):
        super().__init__(str(path))
        self._pending = pending

    @property
    def pending(self):
        return self._pending


@pytest.fixture
def landlock_kernel():
    """Skip unless the running kernel actually enforces Landlock."""
    py_landlock = pytest.importorskip("py_landlock")
    try:
        py_landlock.get_abi_version()
    except py_landlock.LandlockError as e:
        pytest.skip(f"landlock unavailable: {e}")


class TestGating:
    def test_disabled(self, tmp_path, confine):
        opts = options(tmp_path, sandbox=False)
        func = partial(write_denied, tmp_path)
        assert run_confined(confine, opts, func) == "False"

    def test_unavailable_best_effort(self, tmp_path, monkeypatch, confine):
        monkeypatch.setattr(landlock, "Landlock", None)
        assert confine(options(tmp_path)) is None

    def test_unavailable_but_required(self, tmp_path, monkeypatch, confine):
        monkeypatch.setattr(landlock, "Landlock", None)
        with pytest.raises(PkgcoreUserException, match="sandbox unavailable"):
            confine(options(tmp_path, sandbox=True))

    def test_required_refuses_pending_stash(self, tmp_path, landlock_kernel, confine):
        opts = options(tmp_path, sandbox=True, contexts=[stash(tmp_path, pending=True)])
        with pytest.raises(PkgcheckUserException, match="would stash the working tree"):
            confine(opts)

    def test_required_allows_clean_tree(self, tmp_path, landlock_kernel, confine):
        opts = options(tmp_path, sandbox=True, contexts=[stash(tmp_path, pending=False)])
        assert run_confined(confine, opts, lambda: "ran") == "ran"


class TestWritablePaths:
    def test_defaults(self, tmp_path):
        paths = list(sandbox._writable_paths(options(tmp_path)))
        # the paths sourcing an ebuild needs are pkgcore's to add
        assert paths == [str(tmp_path / "cache"), "/dev/shm"]

    def test_repo_writable_while_stashing(self, tmp_path):
        opts = options(tmp_path)
        paths = sandbox._writable_paths(opts, stashing=True)
        assert opts.target_repo.location in paths

    def test_writable_repo_cache_included(self, tmp_path):
        opts = options(tmp_path)
        opts.target_repo.cache = (Namespace(location=str(tmp_path), readonly=False),)
        assert str(tmp_path) in sandbox._writable_paths(opts)


class TestConfinement:
    @pytest.fixture(autouse=True)
    def tmpdir(self, tmp_path, monkeypatch):
        """Move the system temp dir somewhere under tmp_path.

        The real one contains tmp_path itself, which would leave everything
        these tests write to sitting inside an allowed path.
        """
        (path := tmp_path / "tmp").mkdir()
        monkeypatch.setattr(tempfile, "tempdir", str(path))
        return path

    def test_cache_dir_writable(self, tmp_path, landlock_kernel, confine):
        (cache := tmp_path / "cache").mkdir()
        func = partial(write_denied, cache)
        assert run_confined(confine, options(tmp_path), func) == "False"

    def test_multiprocessing_usable(self, tmp_path, landlock_kernel, confine):
        def check():
            import multiprocessing

            multiprocessing.get_context("fork").SimpleQueue()
            return True

        assert run_confined(confine, options(tmp_path), check) == "True"

    def test_repo_writable_while_stashing(self, tmp_path, landlock_kernel, confine):
        (repo := tmp_path / "repo").mkdir()
        opts = options(tmp_path, contexts=[stash(repo, pending=True)])
        func = partial(write_denied, repo)
        assert run_confined(confine, opts, func) == "False"

    def test_repo_readonly_with_nothing_to_stash(self, tmp_path, landlock_kernel, confine):
        (repo := tmp_path / "repo").mkdir()
        opts = options(tmp_path, contexts=[stash(repo, pending=False)])
        func = partial(write_denied, repo)
        assert run_confined(confine, opts, func) == "True"


class TestNetworkConfinement:
    def test_tcp_denied(self, tmp_path, landlock_kernel, confine):
        assert run_confined(confine, options(tmp_path), tcp_denied) == "True"

    def test_tcp_allowed_with_net(self, tmp_path, landlock_kernel, confine):
        opts = options(tmp_path, net=True)
        assert run_confined(confine, opts, tcp_denied) == "False"
