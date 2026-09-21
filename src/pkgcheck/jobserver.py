"""Client for the POSIX jobserver protocol.

See https://www.gnu.org/software/make/manual/html_node/POSIX-Jobserver.html
"""

import os
import select
import shlex

from snakeoil.demandload import regexp

from .log import logger

# jobserver make exports to its children, either a path or a pair of file descriptors
_JOBSERVER_AUTH = regexp(
    r"--jobserver-(?:auth|fds)=(?:fifo:(?P<path>.+)|(?P<read>\d+),(?P<write>\d+))"
)
_MAKEFLAGS_VARS = ("MAKEFLAGS", "MFLAGS", "CARGO_MAKEFLAGS")


def _auth_from_env():
    """Find the jobserver exported in the environment, if any."""
    for var in _MAKEFLAGS_VARS:
        for flag in shlex.split(os.environ.get(var, "")):
            if mo := _JOBSERVER_AUTH.fullmatch(flag):
                return mo
    return None


def path_from_env():
    """Path of the jobserver exported in the environment, if it has one."""
    return mo.group("path") if (mo := _auth_from_env()) else None


def _fds_from_env():
    """Descriptors of the jobserver exported in the environment, if any."""
    if (mo := _auth_from_env()) is None:
        return None
    if path := mo.group("path"):
        return _fds_from_path(path)
    fds = int(mo.group("read")), int(mo.group("write"))
    # make only passes these down to recipes prefixed with "+"
    for fd in fds:
        os.fstat(fd)
    return *fds, False


def _fds_from_path(path):
    """Open a jobserver fifo for both reading and writing, as the protocol requires."""
    fd = os.open(path, os.O_RDWR)
    return fd, fd, True


class JobServer:
    """Holder of job tokens taken from a jobserver.

    Instances are always usable; one that found no jobserver to connect to is
    falsy and simply never hands out a token.
    """

    def __init__(self, read_fd=None, write_fd=None, close=False):
        self._read_fd = read_fd
        self._write_fd = write_fd
        self._close = close
        self._tokens = bytearray()
        self._wake_r = self._wake_w = None
        self._was_blocking = False
        if read_fd is not None:
            # EAGAIN on read then means another client got the token first
            self._was_blocking = os.get_blocking(read_fd)
            os.set_blocking(read_fd, False)
            self._wake_r, self._wake_w = os.pipe()

    @classmethod
    def connect(cls):
        """Connect to the jobserver exported in the environment, if there is one."""
        try:
            fds = _fds_from_env()
        except OSError as exc:
            logger.warning(f"jobserver unavailable: {exc}")
            return cls()
        return cls(*fds) if fds is not None else cls()

    def __bool__(self):
        """Whether there is a jobserver to take tokens from."""
        return self._read_fd is not None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    @property
    def held(self):
        """Number of tokens currently held."""
        return len(self._tokens)

    def acquire(self):
        """Wait for a job token, returning False if stopped or none can be had."""
        while self:
            readable, _, _ = select.select([self._read_fd, self._wake_r], [], [])
            if self._wake_r in readable:
                return False
            try:
                token = os.read(self._read_fd, 1)
            except BlockingIOError:
                continue
            except OSError as exc:
                logger.warning(f"jobserver: failed taking token: {exc}")
                return False
            if not token:  # the jobserver went away
                return False
            self._tokens += token
            return True
        return False

    def stop(self):
        """Interrupt a pending acquire() and refuse to hand out further tokens."""
        if self:
            os.write(self._wake_w, b"\0")

    def release(self):
        """Give every held token back.

        Tokens must be returned by the process that took them, which some
        jobservers enforce, so this has to run before that process exits.
        """
        while self._tokens:
            try:
                os.write(self._write_fd, self._tokens[-1:])
            except OSError as exc:
                logger.warning(f"jobserver: failed returning token: {exc}")
                break
            del self._tokens[-1]

    def close(self):
        """Return all tokens and disconnect."""
        self.release()
        if self._close:
            os.close(self._read_fd)
            if self._write_fd != self._read_fd:
                os.close(self._write_fd)
        elif self:
            # hand an inherited descriptor back the way it was found
            os.set_blocking(self._read_fd, self._was_blocking)
        if self._wake_r is not None:
            os.close(self._wake_r)
            os.close(self._wake_w)
        self._read_fd = self._write_fd = self._wake_r = self._wake_w = None
