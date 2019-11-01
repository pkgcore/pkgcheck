import multiprocessing
import os
import re
import socket
import subprocess
import tempfile

from snakeoil.osutils import pjoin

from .. import const, results, sources
from . import ExplicitlyEnabledCheck


class BadPerlModuleVersion(results.VersionedResult, results.Warning):
    """Package's perl module version that doesn't match its $PV."""

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


class PerlCheck(ExplicitlyEnabledCheck):
    """Perl ebuild related checks."""

    _source = sources.EbuildFileRepoSource
    known_results = frozenset([BadPerlModuleVersion])

    def __init__(self, *args):
        super().__init__(*args)
        self.dist_version_re = re.compile('DIST_VERSION=(?P<dist_version>\d+(\.\d+)*)\s*\n')
        self.process_lock = multiprocessing.Lock()
        self.connection = None
        self.socket_dir = tempfile.TemporaryDirectory(prefix='pkgcheck-')

        # set up Unix domain socket to interoperate with perl side
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        socket_path = os.path.join(self.socket_dir.name, 'perl.socket')
        sock.bind(socket_path)
        sock.listen()

        # start perl client for normalizing perl module versions into package versions
        perl_script = pjoin(const.DATA_PATH, 'perl-version.pl')
        self.perl_client = subprocess.Popen(
            ['perl', perl_script, socket_path], bufsize=1, stderr=subprocess.PIPE)
        sock.settimeout(1)
        try:
            self.connection, _address = sock.accept()
        except socket.timeout as e:
            err = self.perl_client.stderr.read().decode().strip()
            raise Exception(f'failed to connect to perl client: {err}')

    def feed(self, pkg):
        if 'perl-module' in pkg.inherited:
            match = self.dist_version_re.search(''.join(pkg.lines))
            if match is not None:
                dist_version = match.group('dist_version')
                with self.process_lock:
                    self.connection.send(dist_version.encode() + b'\n')
                    size = int(self.connection.recv(2))
                    perl_version = self.connection.recv(size).decode()
                    if perl_version != pkg.version:
                        yield BadPerlModuleVersion(dist_version, perl_version, pkg=pkg)

    def __del__(self):
        if self.connection is not None:
            self.connection.close()
        self.socket_dir.cleanup()
        # at this point, we don't care about being nice to the perl side
        self.perl_client.kill()
