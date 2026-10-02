import os
import threading

import pytest

from pkgcheck import scan
from pkgcheck.jobserver import _MAKEFLAGS_VARS, JobServer


class Pool:
    """A jobserver fifo primed with a number of job tokens."""

    def __init__(self, path, tokens):
        self.path = str(path)
        os.mkfifo(self.path)
        # as the protocol requires, hold it open both ways so it never sees EOF
        self._fd = os.open(self.path, os.O_RDWR)
        self._taken = bytearray()
        os.write(self._fd, b"+" * tokens)

    def _drain(self):
        """Take every token that is free right now."""
        os.set_blocking(self._fd, False)
        try:
            free = bytearray()
            while True:
                try:
                    if not (token := os.read(self._fd, 1)):
                        return free
                except BlockingIOError:
                    return free
                free += token
        finally:
            os.set_blocking(self._fd, True)

    @property
    def available(self):
        """Number of free tokens, put straight back after counting."""
        free = self._drain()
        if free:
            os.write(self._fd, free)
        return len(free)

    def take_all(self):
        """Hold on to every free token, the way a busy build would."""
        self._taken += self._drain()

    def close(self):
        os.close(self._fd)


@pytest.fixture
def pool(tmp_path):
    pool = Pool(tmp_path / "jobserver", tokens=3)
    yield pool
    pool.close()


@pytest.fixture
def makeflags(monkeypatch, pool):
    """Export the pool the way make exports a jobserver to its children."""
    monkeypatch.setenv("MAKEFLAGS", f" -j --jobserver-auth=fifo:{pool.path}")
    return pool


@pytest.fixture(autouse=True)
def only_makeflags(monkeypatch):
    """These tests speak through MAKEFLAGS, so ignore the make running them.

    Make exports the jobserver in MFLAGS as well, which would otherwise stand
    in for a MAKEFLAGS that deliberately has no jobserver in it.
    """
    for var in _MAKEFLAGS_VARS[1:]:
        monkeypatch.delenv(var, raising=False)


class TestJobServer:
    def test_no_jobserver(self, monkeypatch):
        for var in _MAKEFLAGS_VARS:
            monkeypatch.delenv(var, raising=False)
        with JobServer.connect() as jobserver:
            assert not jobserver
            assert not jobserver.acquire()
            assert jobserver.held == 0

    def test_unrelated_makeflags(self, monkeypatch):
        monkeypatch.setenv("MAKEFLAGS", " -j4 --output-sync=target")
        with JobServer.connect() as jobserver:
            assert not jobserver

    def test_missing_fifo(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MAKEFLAGS", f"--jobserver-auth=fifo:{tmp_path / 'nonexistent'}")
        with JobServer.connect() as jobserver:
            assert not jobserver

    def test_unusable_fds(self, monkeypatch):
        """Make only passes its descriptors down to recipes prefixed with '+'."""
        monkeypatch.setenv("MAKEFLAGS", "--jobserver-auth=4242,4243")
        with JobServer.connect() as jobserver:
            assert not jobserver

    def test_last_auth_wins(self, monkeypatch, pool):
        monkeypatch.setenv(
            "MAKEFLAGS", f"-j --jobserver-auth=4242,4243 --jobserver-auth=fifo:{pool.path}"
        )
        with JobServer.connect() as jobserver:
            assert jobserver

    def test_withheld_jobserver(self, monkeypatch, pool):
        """Make 4.4 marks its descriptors as withheld from recipes not prefixed with '+'."""
        fd = os.open(pool.path, os.O_RDWR)
        monkeypatch.setenv("MAKEFLAGS", f"-j --jobserver-auth={fd},{fd} --jobserver-auth=-2,-2")
        try:
            with JobServer.connect() as jobserver:
                assert not jobserver
        finally:
            os.close(fd)

    def test_acquire_and_release(self, makeflags):
        with JobServer.connect() as jobserver:
            assert jobserver
            assert jobserver.acquire()
            assert jobserver.held == 1
            assert makeflags.available == 2
        assert makeflags.available == 3, "tokens weren't returned"

    def test_inherited_fds(self, pool, monkeypatch):
        fd = os.open(pool.path, os.O_RDWR)
        monkeypatch.setenv("MAKEFLAGS", f"--jobserver-auth={fd},{fd}")
        try:
            with JobServer.connect() as jobserver:
                assert jobserver
                assert jobserver.acquire()
                assert pool.available == 2
            assert pool.available == 3, "tokens weren't returned"
            assert os.get_blocking(fd), "an inherited descriptor was left non-blocking"
        finally:
            os.close(fd)

    def test_whole_pool(self, makeflags):
        with JobServer.connect() as jobserver:
            assert all(jobserver.acquire() for _ in range(3))
            assert makeflags.available == 0
            # nothing is free, so this blocks until the scan gives up on growing
            threading.Timer(0.1, jobserver.stop).start()
            assert not jobserver.acquire(), "a token appeared in an empty pool"
            assert jobserver.held == 3

    def test_stopped(self, makeflags):
        with JobServer.connect() as jobserver:
            jobserver.stop()
            assert not jobserver.acquire(), "a stopped client kept taking tokens"
            assert makeflags.available == 3


class TestScanJobserver:
    """Scans throttled by a jobserver still run every check."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        standalone = str(pytest.REPO_ROOT / "testdata/repos/standalone")
        self.args = ["--config", "no", "--cache", "no", "-r", standalone]
        self.args += ["BadCommandsCheck/BannedEapiCommand"]

    def test_tokens_returned(self, makeflags):
        assert list(scan(self.args)), "expected results from a throttled scan"
        assert makeflags.available == 3, "tokens weren't returned"

    def test_exhausted_pool(self, makeflags):
        """A scan that can't get a token runs on the job it was started for."""
        expected = list(scan(self.args))
        makeflags.take_all()
        assert list(scan(self.args)) == expected
