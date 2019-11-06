import pytest
from snakeoil.cli.exceptions import UserException

from pkgcheck.checks import perl

from .. import misc


def perl_deps_missing():
    """Check if perl deps are missing."""
    check = perl.PerlCheck(misc.Options(verbosity=0))
    try:
        check.start()
    except UserException:
        return True
    return False


@pytest.mark.skipif(perl_deps_missing(), reason='perl deps missing')
class TestPerlCheck(misc.ReportTestCase):

    check = perl.PerlCheck(misc.Options(verbosity=0))
    check_kls = perl.PerlCheck

    def mk_pkg(self, dist_version, PVR, **kwargs):
        lines = [
            'inherit perl-module\n',
            f'DIST_VERSION={dist_version}\n',
        ]
        kwargs.setdefault('EAPI', '7')
        kwargs.setdefault('_eclasses_', ['perl-module'])
        return misc.FakePkg(f'app-foo/bar-{PVR}', lines=lines, data=kwargs)

    def test_matching(self):
        for PVR in ('1.7.0-r0', '1.7.0', '1.7.0-r100'):
            self.assertNoReport(self.check, self.mk_pkg('1.007', PVR))

    def test_nonmatching(self):
        for PVR in ('1.7.0-r0', '1.7.0', '1.7.0-r100'):
            r = self.assertReport(self.check, self.mk_pkg('1.07', PVR))
            assert r.dist_version == '1.07'
            assert r.perl_version == '1.70.0'
            assert '1.07 -> 1.70.0' in str(r)
            r = self.assertReport(self.check, self.mk_pkg('1.7', PVR))
            assert r.dist_version == '1.7'
            assert r.perl_version == '1.700.0'
            assert '1.7 -> 1.700.0' in str(r)
