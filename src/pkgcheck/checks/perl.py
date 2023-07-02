import multiprocessing
import re
import subprocess

from pkgcore.ebuild.atom import atom as atom_cls
from pkgcore.restrictions import packages, values
from pkgcore.package.errors import MetadataException
from snakeoil.osutils import pjoin
from snakeoil.sequences import iflatten_instance

from .. import const, results, sources
from . import OptionalCheck, SkipCheck


class MismatchedPerlVersion(results.VersionResult, results.Warning):
    """A package's normalized perl module version doesn't match its $PV."""

    def __init__(self, dist_version, normalized, **kwargs):
        super().__init__(**kwargs)
        self.dist_version = dist_version
        self.normalized = normalized

    @property
    def desc(self):
        return f"DIST_VERSION={self.dist_version} normalizes to {self.normalized}"


class MissingVersionedVirtualPerlDependency(results.VersionResult, results.Warning):
    """Missing version restriction for virtual perl dependency.

    The virtuals ``virtual/perl-*`` stand for packages that have releases both
    as part of ``dev-lang/perl`` and standalone in ``perl-core/*``. Apart from
    rare special cases, if you require "any" version of such a virtual, this
    will always be fulfilled by ``dev-lang/perl``.
    """

    def __init__(self, atom, **kwargs):
        super().__init__(**kwargs)
        self.atom = atom

    @property
    def desc(self):
        return f"missing version restriction for virtual perl: {self.atom!r}"


class _PerlException(Exception):
    """Generic error during perl script initialization."""


class _PerlConnection:
    """Connection to perl script the check is going to communicate with."""

    def __init__(self, options):
        self.perl_client = None
        self.process_lock = multiprocessing.Lock()

        # start perl client for normalizing perl module versions into package versions
        try:
            self.perl_client = subprocess.Popen(
                ["perl", pjoin(const.DATA_PATH, "perl-version.pl")],
                text=True,
                bufsize=1,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError:
            raise _PerlException("perl not installed on system")

        # check if the script is running
        ready = self.perl_client.stdout.readline().strip()
        if ready != "ready" or self.perl_client.poll():
            err_msg = "failed to run perl script"
            if options.verbosity > 0:
                stderr = self.perl_client.stderr.read().strip()
                err_msg += f": {stderr}"
            raise _PerlException(err_msg)

    def normalize(self, version):
        """Normalize a given version number to its perl equivalent."""
        with self.process_lock:
            self.perl_client.stdin.write(version + "\n")
            return self.perl_client.stdout.readline().strip()

    def __del__(self):
        # kill perl process if it still exists
        if self.perl_client is not None:
            self.perl_client.kill()


class PerlCheck(OptionalCheck):
    """Perl ebuild related checks."""

    _source = sources.EbuildFileRepoSource
    known_results = frozenset(
        {
            MismatchedPerlVersion,
            MissingVersionedVirtualPerlDependency,
        }
    )

    def __init__(self, *args):
        super().__init__(*args)
        self.dist_version_re = re.compile(r"DIST_VERSION=(?P<dist_version>\d+(\.\d+)*)\s*\n")
        # Initialize connection with perl script. This is done during
        # __init__() since only one running version of the script is shared
        # between however many scanning processes will be run. Also, it makes
        # it easier to disable this check if required perl deps are missing.
        try:
            self.perl = _PerlConnection(self.options)
        except _PerlException as exc:
            raise SkipCheck(self, str(exc))

    def feed(self, pkg):
        if "perl-module" in pkg.inherited:
            if mo := self.dist_version_re.search("".join(pkg.lines)):
                dist_version = mo.group("dist_version")
                normalized = self.perl.normalize(dist_version)
                if normalized != pkg.version:
                    yield MismatchedPerlVersion(dist_version, normalized, pkg=pkg)

        missing_virtual_perl = set()
        for attr in (x.lower() for x in pkg.eapi.dep_keys):
            try:
                deps = getattr(pkg, attr)
            except MetadataException:
                continue
            for atom in iflatten_instance(deps, (atom_cls,)):
                if (
                    not atom.op
                    and atom.key.startswith("virtual/perl-")
                    and pkg.key != "dev-lang/perl"
                    and pkg.category != "perl-core"
                    and not pkg.key.startswith("virtual/perl-")
                ):
                    missing_virtual_perl.add(str(atom))

        for atom in sorted(missing_virtual_perl):
            yield MissingVersionedVirtualPerlDependency(str(atom), pkg=pkg)
