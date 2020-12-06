import multiprocessing
import re
import subprocess

from pkgcore.restrictions import packages, values
from snakeoil.osutils import pjoin

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
        return f'DIST_VERSION={self.dist_version} normalizes to {self.normalized}'


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
                ['perl', pjoin(const.DATA_PATH, 'perl-version.pl')],
                text=True, bufsize=1,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except FileNotFoundError:
            raise _PerlException('perl not installed on system')

        # check if the script is running
        ready = self.perl_client.stdout.readline().strip()
        if ready != 'ready' or self.perl_client.poll():
            err_msg = 'failed to run perl script'
            if options.verbosity > 0:
                stderr = self.perl_client.stderr.read().strip()
                err_msg += f': {stderr}'
            raise _PerlException(err_msg)

    def normalize(self, version):
        """Normalize a given version number to its perl equivalent."""
        with self.process_lock:
            self.perl_client.stdin.write(version + '\n')
            return self.perl_client.stdout.readline().strip()

    def __del__(self):
        # kill perl process if it still exists
        if self.perl_client is not None:
            self.perl_client.kill()


class PerlCheck(OptionalCheck):
    """Perl ebuild related checks."""

    _restricted_source = (sources.RestrictionRepoSource, (
        packages.PackageRestriction('inherited', values.ContainmentMatch2('perl-module')),))
    _source = (sources.EbuildFileRepoSource, (), (('source', _restricted_source),))
    known_results = frozenset([MismatchedPerlVersion])

    def __init__(self, *args):
        super().__init__(*args)
        self.dist_version_re = re.compile(r'DIST_VERSION=(?P<dist_version>\d+(\.\d+)*)\s*\n')
        # Initialize connection with perl script. This is done during
        # __init__() since only one running version of the script is shared
        # between however many scanning processes will be run. Also, it makes
        # it easier to disable this check if required perl deps are missing.
        try:
            self.perl = _PerlConnection(self.options)
        except _PerlException as e:
            raise SkipCheck(self, str(e))

    def feed(self, pkg):
        if mo := self.dist_version_re.search(''.join(pkg.lines)):
            dist_version = mo.group('dist_version')
            normalized = self.perl.normalize(dist_version)
            if normalized != pkg.version:
                yield MismatchedPerlVersion(dist_version, normalized, pkg=pkg)
