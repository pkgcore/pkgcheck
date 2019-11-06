import socket
from unittest.mock import patch

import pytest

from pkgcheck.checks import FailedCheckInit, perl

from .. import misc

REASON = ''


def perl_deps_missing():
    """Check if perl deps are missing."""
    global REASON
    check = perl.PerlCheck(misc.Options(verbosity=1))
    try:
        check.start()
    except FailedCheckInit as e:
        REASON = str(e)
        return True
    return False


@pytest.mark.skipif(perl_deps_missing(), reason=REASON)
class TestPerlCheck(misc.ReportTestCase):

    check = perl.PerlCheck(misc.Options(verbosity=0))
    check_kls = perl.PerlCheck

    def mk_pkg(self, PVR, dist_version='', eclasses=('perl-module',), **kwargs):
        lines = ['inherit perl-module\n']
        if dist_version:
            lines.append(f'DIST_VERSION={dist_version}\n')
        kwargs.setdefault('EAPI', '7')
        kwargs.setdefault('_eclasses_', list(eclasses))
        return misc.FakePkg(f'app-foo/bar-{PVR}', lines=lines, data=kwargs)

    def test_matching(self):
        """Ebuilds with matching DIST_VERSION and package version."""
        for PVR in ('1.7.0-r0', '1.7.0', '1.7.0-r100'):
            self.assertNoReport(self.check, self.mk_pkg(PVR, '1.007'))

    def test_nonmatching(self):
        """Ebuilds without matching DIST_VERSION and package version."""
        for PVR in ('1.7.0-r0', '1.7.0', '1.7.0-r100'):
            r = self.assertReport(self.check, self.mk_pkg(PVR, '1.07'))
            assert r.dist_version == '1.07'
            assert r.perl_version == '1.70.0'
            assert '1.07 -> 1.70.0' in str(r)
            r = self.assertReport(self.check, self.mk_pkg(PVR, '1.7'))
            assert r.dist_version == '1.7'
            assert r.perl_version == '1.700.0'
            assert '1.7 -> 1.700.0' in str(r)

    def test_no_perl_module_eclass_inherit(self):
        """Ebuilds that don't inherit the perl-module eclass are skipped."""
        self.assertNoReport(self.check, self.mk_pkg('1.7.0', '1.07', eclasses=()))

    def test_no_dist_version(self):
        """Ebuilds without DIST_VERSION defined are skipped."""
        self.assertNoReport(self.check, self.mk_pkg('1.7.0'))

    def test_no_perl(self):
        """Check initialization fails if perl isn't installed."""
        with patch('subprocess.Popen') as popen:
            popen.side_effect = FileNotFoundError('perl not available')
            check = perl.PerlCheck(misc.Options(verbosity=0))
            with pytest.raises(FailedCheckInit) as excinfo:
                check.start()
            assert 'perl not installed' in str(excinfo.value)

    def test_no_perl_deps(self):
        """Check initialization fails if perl deps aren't installed."""
        with patch('socket.socket') as mock_socket:
            mock_socket.return_value.accept.side_effect = socket.timeout
            for verbosity in (0, 1):
                check = perl.PerlCheck(misc.Options(verbosity=verbosity))
                with pytest.raises(FailedCheckInit) as excinfo:
                    check.start()
                assert 'failed to connect to perl client' in str(excinfo.value)
