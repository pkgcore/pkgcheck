import errno
import multiprocessing
import os
import re
import socket
import subprocess
import tempfile

from snakeoil.osutils import pjoin

from .. import const, results, sources
from . import Check, SkipOptionalCheck


class BadPerlModuleVersion(results.VersionedResult, results.Warning):
    """A package's perl module version doesn't match its $PV."""

    def __init__(self, dist_version, perl_version, **kwargs):
        super().__init__(**kwargs)
        self.dist_version = dist_version
        self.perl_version = perl_version

    @property
    def desc(self):
        return (
            "module version doesn't match package version: "
            f'{self.dist_version} -> {self.perl_version}'
        )


class PerlCheck(Check):
    """Perl ebuild related checks."""

    _source = sources.EbuildFileRepoSource
    known_results = frozenset([BadPerlModuleVersion])

    def __init__(self, *args):
        super().__init__(*args)
        self.dist_version_re = re.compile('DIST_VERSION=(?P<dist_version>\d+(\.\d+)*)\s*\n')
        self.connection = None
        self.perl_client = None
        self.process_lock = multiprocessing.Lock()
        self.socket_dir = tempfile.TemporaryDirectory(prefix='pkgcheck-')

        # set up Unix domain socket to communicate with perl client
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        socket_path = os.path.join(self.socket_dir.name, 'perl.socket')
        try:
            sock.bind(socket_path)
        except OSError as e:
            if e.errno == errno.EADDRINUSE:
                # socket already set up by a previous run
                return
            raise
        sock.listen()

        # start perl client for normalizing perl module versions into package versions
        perl_script = pjoin(const.DATA_PATH, 'perl-version.pl')
        try:
            self.perl_client = subprocess.Popen(
                ['perl', perl_script, socket_path], bufsize=1, stderr=subprocess.PIPE)
        except FileNotFoundError:
            raise SkipOptionalCheck(self, 'perl not installed on system')

        sock.settimeout(1)
        try:
            self.connection, _address = sock.accept()
        except socket.timeout:
            err_msg = 'failed to connect to perl client'
            if self.options.verbosity > 0:
                stderr = self.perl_client.stderr.read().decode().strip()
                err_msg += f': {stderr}'
            raise SkipOptionalCheck(self, err_msg)

    def feed(self, pkg):
        if 'perl-module' in pkg.inherited:
            match = self.dist_version_re.search(''.join(pkg.lines))
            if match is not None:
                dist_version = match.group('dist_version')
                with self.process_lock:
                    self.connection.send(dist_version.encode() + b'\n')
                    size = int(self.connection.recv(2))
                    perl_version = self.connection.recv(size).decode('utf-8', 'replace')
                    if perl_version != pkg.version:
                        yield BadPerlModuleVersion(dist_version, perl_version, pkg=pkg)

    def __del__(self):
        if self.connection is not None:
            self.connection.close()
        self.socket_dir.cleanup()
        # at this point, we don't care about being nice to the perl side
        if self.perl_client is not None:
            self.perl_client.kill()
