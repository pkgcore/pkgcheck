from pkgcore.test.misc import FakePkg

from pkgcheck import glep73, metadata_checks, addons
from pkgcheck.test import misc
from pkgcheck.test.test_metadata_checks import iuse_options


class TestGLEP73(iuse_options, misc.ReportTestCase):

    check_kls = metadata_checks.RequiredUSEMetadataReport

    def setUp(self):
        super(TestGLEP73, self).setUp()
        options = self.get_options(verbose=1,
                                   use_desc=('a', 'b', 'c'))
        profiles = {'x86': [misc.FakeProfile(name='default/linux/x86')]}
        self.check = metadata_checks.RequiredUSEMetadataReport(
            options, addons.UseAddon(options, profiles['x86']), profiles)
        self.check.start()

    def mk_pkg(self, eapi="5", iuse="", required_use="", keywords="x86"):
        return FakePkg(
            "dev-foo/bar-1",
            eapi=eapi,
            iuse=iuse.split(),
            data={"REQUIRED_USE": required_use, "KEYWORDS": keywords})

    def test_syntax(self):
        # ||/??/^^ can only contain plain flags
        r = self.assertReport(self.check, self.mk_pkg(iuse="+a b c", required_use="|| ( a ( b c ) )"))
        self.assertIsInstance(r, glep73.GLEP73Syntax)
        r = self.assertReport(self.check, self.mk_pkg(iuse="+a b c", required_use="|| ( a b? ( c ) )"))
        self.assertIsInstance(r, glep73.GLEP73Syntax)
        r = self.assertReport(self.check, self.mk_pkg(iuse="+a b c", required_use="|| ( a || ( b c ) )"))
        self.assertIsInstance(r, glep73.GLEP73Syntax)
        r = self.assertReport(self.check, self.mk_pkg(iuse="+a b c", required_use="|| ( a ?? ( b c ) )"))
        self.assertIsInstance(r, glep73.GLEP73Syntax)
        r = self.assertReport(self.check, self.mk_pkg(iuse="+a b c", required_use="|| ( a ^^ ( b c ) )"))
        self.assertIsInstance(r, glep73.GLEP73Syntax)
        r = self.assertReport(self.check, self.mk_pkg(iuse="+a b c", required_use="?? ( a ( b c ) )"))
        self.assertIsInstance(r, glep73.GLEP73Syntax)
        r = self.assertReport(self.check, self.mk_pkg(iuse="+a b c", required_use="?? ( a b? ( c ) )"))
        self.assertIsInstance(r, glep73.GLEP73Syntax)
        r = self.assertReport(self.check, self.mk_pkg(iuse="+a b c", required_use="?? ( a || ( b c ) )"))
        self.assertIsInstance(r, glep73.GLEP73Syntax)
        r = self.assertReport(self.check, self.mk_pkg(iuse="+a +b +c", required_use="?? ( a ?? ( b c ) )"))
        self.assertIsInstance(r, glep73.GLEP73Syntax)
        r = self.assertReport(self.check, self.mk_pkg(iuse="+a b c", required_use="?? ( a ^^ ( b c ) )"))
        self.assertIsInstance(r, glep73.GLEP73Syntax)
        r = self.assertReport(self.check, self.mk_pkg(iuse="+a b c", required_use="^^ ( a ( b c ) )"))
        self.assertIsInstance(r, glep73.GLEP73Syntax)
        r = self.assertReport(self.check, self.mk_pkg(iuse="+a b c", required_use="^^ ( a b? ( c ) )"))
        self.assertIsInstance(r, glep73.GLEP73Syntax)
        r = self.assertReport(self.check, self.mk_pkg(iuse="+a b c", required_use="^^ ( a || ( b c ) )"))
        self.assertIsInstance(r, glep73.GLEP73Syntax)
        r = self.assertReport(self.check, self.mk_pkg(iuse="+a +b +c", required_use="^^ ( a ?? ( b c ) )"))
        self.assertIsInstance(r, glep73.GLEP73Syntax)
        r = self.assertReport(self.check, self.mk_pkg(iuse="+a b c", required_use="^^ ( a ^^ ( b c ) )"))
        self.assertIsInstance(r, glep73.GLEP73Syntax)

    def test_syntax_allof(self):
        # all-of groups in meaningless contexts
        r = self.assertReport(self.check, self.mk_pkg(iuse="+a +b", required_use="( a b )"))
        self.assertIsInstance(r, glep73.GLEP73Syntax)
        r = self.assertReport(self.check, self.mk_pkg(iuse="a b c", required_use="a? ( ( b c ) )"))
        self.assertIsInstance(r, glep73.GLEP73Syntax)
    test_syntax_allof.todo = "meaningless all-of groups are collapsed by pkgcore"
