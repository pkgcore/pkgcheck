"""Confinement of scanning runs using the Landlock LSM.

Scanning a repo is a read-only operation, but generating metadata means
sourcing ebuilds with bash, which runs code from the repo under scan.  This
drops write access to everything outside the few paths a scan legitimately
writes, and blocks outgoing TCP unless network checks were enabled.

Landlock restrictions cannot be lifted and are inherited by child processes, so
this only ever runs from a command's main function -- never from
:py:func:`pkgcheck.api.scan`, whose caller goes on living afterwards.
"""

import os
import tempfile

from snakeoil.contexts import GitStash

from .base import PkgcheckUserException
from .log import logger

try:
    from py_landlock import AccessFs, Landlock, LandlockError

    # Rights granted on a writable directory and everything beneath it.  Fifos
    # and sockets are included for the sake of the temp dir: bash falls back to
    # a named pipe for process substitution when built without /dev/fd support,
    # and multiprocessing uses a unix socket for non-fork start methods.
    _DIR_RW = (
        AccessFs.READ_FILE
        | AccessFs.READ_DIR
        | AccessFs.WRITE_FILE
        | AccessFs.TRUNCATE
        | AccessFs.MAKE_REG
        | AccessFs.MAKE_DIR
        | AccessFs.MAKE_SYM
        | AccessFs.MAKE_FIFO
        | AccessFs.MAKE_SOCK
        | AccessFs.REMOVE_FILE
        | AccessFs.REMOVE_DIR
        | AccessFs.REFER
        | AccessFs.EXECUTE
    )
    # Rights granted on a writable file.  Directory-only rights have to be left
    # out: the kernel rejects the entire rule for a non-directory rather than
    # ignoring the ones that don't apply.  Ioctls are only meaningful for the
    # device nodes below, and only for ones opened after the ruleset applies:
    # inherited descriptors such as a terminal on stdin are never affected.
    _FILE_RW = AccessFs.READ_FILE | AccessFs.WRITE_FILE | AccessFs.TRUNCATE | AccessFs.IOCTL_DEV
except ImportError:  # pragma: no cover
    Landlock = None


def _metadata_caches(options):
    """Metadata cache locations pkgcore considers writable"""
    for repo in options.target_repo.trees:
        for cache in getattr(repo, "cache", ()):
            if cache.readonly:
                continue
            # pkgcore creates a missing cache dir on demand and decides
            # writability from the closest existing parent, so grant that
            path = cache.location
            while not os.path.exists(path):
                if (parent := os.path.dirname(path)) == path:
                    break
                path = parent
            yield path


def _pending_stash(options):
    """Whether scanning will stash working tree changes away and back again."""
    return any(c.pending for c in options.contexts if isinstance(c, GitStash))


def _writable_paths(options, *, stashing=False):
    """All paths a scan of the given targets needs write access to."""
    yield options.cache_dir
    # git config files, the historical repo --commits builds, and bash's
    # here-documents that outgrow a pipe all land here.  This can't be narrowed
    # to a directory private to the run: pkgcore hands the ebuild daemon a
    # minimal environment, so the bash sourcing ebuilds never sees a redirected
    # TMPDIR and falls back to the system one regardless.
    yield tempfile.gettempdir()
    # multiprocessing's queues and pools need POSIX semaphores
    yield "/dev/shm"
    # opened read-write by subprocess.DEVNULL, among others
    yield "/dev/null"
    # sandbox(1) reports access violations here, and losing them would hide the
    # very misbehaviour worth knowing about.  Nothing an attacker gains: the
    # inherited output descriptors already point at the same terminal.
    yield "/dev/tty"
    yield from _metadata_caches(options)
    if stashing:
        # --commits and --staged stash the working tree around the scan, and
        # unstash it once the pipeline is done, so the repo has to stay
        # writable for the lifetime of the confinement
        yield options.target_repo.location


def _unavailable(required: bool, msg: str):
    """Fail or note that the sandbox couldn't be set up."""
    if required:
        raise PkgcheckUserException(f"sandbox unavailable: {msg}")
    logger.debug("skipping landlock sandbox: %s", msg)


def confine(options) -> None:
    """Drop write and network access that scanning doesn't need.

    Best effort by default, so an old or unconfigurable kernel just leaves the
    run unconfined.  Requesting ``--sandbox y`` explicitly turns that into an
    error instead, and ``--sandbox n`` skips this entirely.
    """
    if options.sandbox is False:
        return
    required = options.sandbox is True

    if Landlock is None:
        _unavailable(required, "py-landlock is not installed")
        return

    # keeping the repo writable is a fallback, not something to do behind the
    # back of someone who asked for confinement outright
    stashing = _pending_stash(options)
    if stashing and required:
        raise PkgcheckUserException(
            "sandbox requested, but --commits/--staged would stash the working "
            "tree, which needs write access to the repo being scanned; commit "
            "or stash the changes first, or pass --sandbox=n"
        )

    try:
        sandbox = Landlock(strict=False)
        # scoping signals and abstract sockets isn't what this is for
        sandbox.allow_all_scope()
        if options.net:
            sandbox.allow_all_network()
        # the whole filesystem stays readable and executable; this only takes
        # away the ability to write to it
        sandbox.add_path_rule("/", access=AccessFs.READ_FILE | AccessFs.READ_DIR | AccessFs.EXECUTE)
        for path in _writable_paths(options, stashing=stashing):
            if os.path.isdir(path):
                sandbox.add_path_rule(path, access=_DIR_RW)
            elif os.path.exists(path):
                sandbox.add_path_rule(path, access=_FILE_RW)
            else:
                logger.debug("landlock sandbox: no such path, skipping: %r", path)
        sandbox.apply()
    except (LandlockError, OSError) as e:
        _unavailable(required, str(e))
        return

    logger.debug("landlock sandbox applied, ABI %s", sandbox.abi_version)
