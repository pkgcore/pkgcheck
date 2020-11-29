import errno
import multiprocessing
import os
import re
import socket
import subprocess
import tempfile

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
        self.connection = None
        self.perl_client = None
        self.process_lock = multiprocessing.Lock()
        self.socket_dir = tempfile.TemporaryDirectory(prefix='pkgcheck-')

        # set up Unix domain socket to communicate with perl client
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        socket_path = os.path.join(self.socket_dir.name, 'perl.socket')
        sock.bind(socket_path)
        sock.listen()

        # start perl client for normalizing perl module versions into package versions
        perl_script = pjoin(const.DATA_PATH, 'perl-version.pl')
        try:
            self.perl_client = subprocess.Popen(
                ['perl', perl_script, socket_path], stderr=subprocess.PIPE)
        except FileNotFoundError:
            raise _PerlException('perl not installed on system')

        sock.settimeout(1)
        try:
            self.connection, _address = sock.accept()
        except socket.timeout:
            err_msg = 'failed to connect to perl client'
            if options.verbosity > 0:
                stderr = self.perl_client.stderr.read().decode().strip()
                err_msg += f': {stderr}'
            raise _PerlException(err_msg)

    def normalize(self, version):
        """Normalize a given version number to its perl equivalent."""
        with self.process_lock:
            self.connection.send(version.encode() + b'\n')
            size = int(self.connection.recv(2))
            return self.connection.recv(size).decode('utf-8', 'replace')

    def __del__(self):
        # Clean up perl cruft if it exists, we don't care about being nice to
        # the perl side at this point.
        if self.connection is not None:
            self.connection.close()
        try:
            self.socket_dir.cleanup()
        except FileNotFoundError:
            pass
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
        match = self.dist_version_re.search(''.join(pkg.lines))
        if match is not None:
            dist_version = match.group('dist_version')
            normalized = self.perl.normalize(dist_version)
            if normalized != pkg.version:
                yield MismatchedPerlVersion(dist_version, normalized, pkg=pkg)
