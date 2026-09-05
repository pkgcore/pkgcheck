"""Confinement of scanning runs, on top of :py:mod:`pkgcore.landlock`.

Scanning a repo is a read-only operation, but generating metadata means
sourcing ebuilds with bash, which runs code from the repo under scan.  This
works out what a scan legitimately writes and hands that to pkgcore, which
takes away the rest along with outgoing TCP.

Confinement cannot be lifted and is inherited by child processes, so this only
ever runs from a command's main function -- never from
:py:func:`pkgcheck.api.scan`, whose caller goes on living afterwards.
"""

from pkgcore import landlock
from snakeoil.contexts import GitStash

from .base import PkgcheckUserException
from .log import logger


def _writable_paths(options, *, stashing=False):
    """All paths a scan of the given targets needs write access to."""
    yield options.cache_dir
    # multiprocessing's queues and pools need POSIX semaphores
    yield "/dev/shm"
    # sourcing an ebuild is expensive, so a repo keeps the cache access it
    # already had; dropping it would silently re-source every ebuild on every
    # run, as pkgcheck mutes the warning pkgcore logs when a cache write fails
    yield from landlock.writable_cache_paths(*options.target_repo.trees)
    if stashing:
        # --commits and --staged stash the working tree around the scan, and
        # unstash it once the pipeline is done, so the repo has to stay
        # writable for the lifetime of the confinement
        yield options.target_repo.location


def confine(options) -> None:
    """Drop write and network access that scanning doesn't need.

    Best effort by default, so an old or unconfigurable kernel just leaves the
    run unconfined.  Requesting ``--sandbox=y`` explicitly turns that into an
    error instead, and ``--sandbox=n`` skips this entirely.
    """
    if options.sandbox is False:
        return
    required = options.sandbox is True

    # keeping the repo writable is a fallback, not something to do behind the
    # back of someone who asked for confinement outright
    stashing = any(c.pending for c in options.contexts if isinstance(c, GitStash))
    if stashing and required:
        raise PkgcheckUserException(
            "sandbox requested, but --commits/--staged would stash the working tree, which needs write "
            "access to the repo being scanned; commit or stash the changes first, or pass --sandbox=n"
        )

    if landlock.confine(
        *_writable_paths(options, stashing=stashing),
        allow_net=bool(options.net),
        required=required,
    ):
        # pkgcore's own logging is muted here, so say it ourselves
        logger.debug("landlock sandbox applied")
