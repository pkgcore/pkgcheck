from pkgcore.test.misc import FakePkg

from pkgcheck import glep73, metadata_checks, addons
from pkgcheck.test import misc
from pkgcheck.test.test_metadata_checks import iuse_options


class TestGLEP73(iuse_options, misc.ReportTestCase):

    check_kls = metadata_checks.RequiredUSEMetadataReport

    def setUp(self):
        super(TestGLEP73, self).setUp()
        options = self.get_options(verbose=1,
                                   use_desc=('a', 'b', 'c', 'd'))
        profile = misc.FakeProfile(name='default/linux/x86',
            forced_use={
                'dev-foo/a-forced': ['a'],
                'dev-foo/a-b-forced': ['a', 'b'],
                'dev-foo/b-forced': ['b'],
                'dev-foo/a-forced-b-masked': ['a'],
                'dev-foo/a-masked-b-forced': ['b'],
            },
            masked_use={
                'dev-foo/a-masked': ['a'],
                'dev-foo/a-b-masked': ['a', 'b'],
                'dev-foo/b-masked': ['b'],
                'dev-foo/a-forced-b-masked': ['b'],
                'dev-foo/a-masked-b-forced': ['a'],
            })

        profiles = {'x86': [profile]}
        self.check = metadata_checks.RequiredUSEMetadataReport(
            options, addons.UseAddon(options, profiles['x86']), profiles)
        self.check.start()

    def mk_pkg(self, eapi="5", iuse="", required_use="", keywords="x86",
               cpv="dev-foo/bar-1"):
        return FakePkg(
            cpv,
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

    def test_flatten(self):
        """Test common cases for flattening"""
        f = glep73.GLEP73Flag
        nf = lambda x: glep73.GLEP73Flag(x, negate=True)

        # flat constraints
        p = self.mk_pkg(iuse="a b", required_use="a b")
        self.assertListEqual(glep73.glep73_flatten(p.required_use),
                [([], f('a')), ([], f('b'))])
        p = self.mk_pkg(iuse="a b", required_use="a !b")
        self.assertListEqual(glep73.glep73_flatten(p.required_use),
                [([], f('a')), ([], nf('b'))])

        # easy conditions
        p = self.mk_pkg(iuse="a b c", required_use="a? ( b ) b? ( c )")
        self.assertListEqual(glep73.glep73_flatten(p.required_use),
                [([f('a')], f('b')), ([f('b')], f('c'))])
        p = self.mk_pkg(iuse="a b c", required_use="a? ( b? ( c ) )")
        self.assertListEqual(glep73.glep73_flatten(p.required_use),
                [([f('a'), f('b')], f('c'))])
        p = self.mk_pkg(iuse="a b c d", required_use="a? ( b? ( c d ) )")
        self.assertListEqual(glep73.glep73_flatten(p.required_use),
                [([f('a'), f('b')], f('c')), ([f('a'), f('b')], f('d'))])
        p = self.mk_pkg(iuse="a b c d", required_use="a? ( b? ( c ) d )")
        self.assertListEqual(glep73.glep73_flatten(p.required_use),
                [([f('a'), f('b')], f('c')), ([f('a')], f('d'))])

        # ||/??/^^ groups
        p = self.mk_pkg(iuse="a b c", required_use="|| ( a b c )")
        self.assertListEqual(glep73.glep73_flatten(p.required_use),
                [([nf('b'), nf('c')], f('a'))])
        p = self.mk_pkg(iuse="a b c", required_use="?? ( a b c )")
        self.assertListEqual(glep73.glep73_flatten(p.required_use),
                [([f('a')], nf('b')), ([f('a')], nf('c')), ([f('b')], nf('c'))])
        p = self.mk_pkg(iuse="a b c", required_use="^^ ( a b c )")
        self.assertListEqual(glep73.glep73_flatten(p.required_use),
                [([nf('b'), nf('c')], f('a')),
                 ([f('a')], nf('b')), ([f('a')], nf('c')), ([f('b')], nf('c'))])

        # ||/??/^^ groups in a conditional
        p = self.mk_pkg(iuse="a b c d", required_use="d? ( || ( a b c ) )")
        self.assertListEqual(glep73.glep73_flatten(p.required_use),
                [([f('d'), nf('b'), nf('c')], f('a'))])
        p = self.mk_pkg(iuse="a b c d", required_use="d? ( ?? ( a b c ) )")
        self.assertListEqual(glep73.glep73_flatten(p.required_use),
                [([f('d'), f('a')], nf('b')), ([f('d'), f('a')], nf('c')),
                 ([f('d'), f('b')], nf('c'))])
        p = self.mk_pkg(iuse="a b c d", required_use="d? ( ^^ ( a b c ) )")
        self.assertListEqual(glep73.glep73_flatten(p.required_use),
                [([f('d'), nf('b'), nf('c')], f('a')),
                 ([f('d'), f('a')], nf('b')), ([f('d'), f('a')], nf('c')),
                 ([f('d'), f('b')], nf('c'))])

    def test_flatten_identity(self):
        """Test whether identity of flags is preserved while flattening"""
        p = self.mk_pkg(iuse="a b c", required_use="a? ( b c )")
        pf = glep73.glep73_flatten(p.required_use)
        self.assertIs(pf[0][0][0], pf[1][0][0])

        p = self.mk_pkg(iuse="a b c", required_use="a? ( b ) a? ( c )")
        pf = glep73.glep73_flatten(p.required_use)
        self.assertIsNot(pf[0][0][0], pf[1][0][0])

    def test_flatten_with_immutables(self):
        """Test whether constraints with immutable reordering are
        flattened correctly"""
        f = glep73.GLEP73Flag
        nf = lambda x: glep73.GLEP73Flag(x, negate=True)

        p = self.mk_pkg(iuse="a b c", required_use="|| ( a b c )")
        self.assertListEqual(glep73.glep73_flatten(p.required_use,
                                                   {'c': True}),
                [([nf('a'), nf('b')], f('c'))])

        p = self.mk_pkg(iuse="a b c", required_use="|| ( a b c )")
        self.assertListEqual(glep73.glep73_flatten(p.required_use,
                                                   {'a': False}),
                [([nf('c'), nf('a')], f('b'))])

        p = self.mk_pkg(iuse="a b c", required_use="|| ( a b c )")
        self.assertListEqual(glep73.glep73_flatten(p.required_use,
                                                   {'a': False, 'c': True}),
                [([nf('b'), nf('a')], f('c'))])

        # check whether relative ordering is preserved within forced/masked flags
        p = self.mk_pkg(iuse="a b c", required_use="|| ( a b c )")
        self.assertListEqual(glep73.glep73_flatten(p.required_use,
                                                   {'b': True, 'c': True}),
                [([nf('c'), nf('a')], f('b'))])

        p = self.mk_pkg(iuse="a b c", required_use="|| ( a b c )")
        self.assertListEqual(glep73.glep73_flatten(p.required_use,
                                                   {'a': False, 'b': False}),
                [([nf('a'), nf('b')], f('c'))])

    def test_immutability_check(self):
        """Test immutability errors."""
        self.assertNoReport(self.check, self.mk_pkg(cpv="dev-foo/a-masked-1",
            iuse="a b", required_use="a? ( b )"))
        r = self.assertReport(self.check, self.mk_pkg(cpv="dev-foo/b-masked-1",
            iuse="a b", required_use="a? ( b )"))
        self.assertIsInstance(r, glep73.GLEP73Immutability)
        self.assertNoReport(self.check, self.mk_pkg(cpv="dev-foo/a-b-masked-1",
            iuse="a b", required_use="a? ( b )"))
        self.assertNoReport(self.check, self.mk_pkg(cpv="dev-foo/a-forced-1",
            iuse="a +b", required_use="a? ( b )"))
        self.assertNoReport(self.check, self.mk_pkg(cpv="dev-foo/b-forced-1",
            iuse="a +b", required_use="a? ( b )"))
        self.assertNoReport(self.check, self.mk_pkg(cpv="dev-foo/a-b-forced-1",
            iuse="a b", required_use="a? ( b )"))
        r = self.assertReports(self.check, self.mk_pkg(cpv="dev-foo/a-forced-b-masked-1",
            iuse="a b", required_use="a? ( b )"))
        self.assertIsInstance(r[-1], glep73.GLEP73Immutability)
        self.assertNoReport(self.check, self.mk_pkg(cpv="dev-foo/b-forced-a-masked-1",
            iuse="a b", required_use="a? ( b )"))

        self.assertNoReport(self.check, self.mk_pkg(cpv="dev-foo/a-masked-1",
            iuse="a b", required_use="a? ( b )"))
        self.assertNoReport(self.check, self.mk_pkg(cpv="dev-foo/b-masked-1",
            iuse="a b", required_use="a? ( !b )"))
        self.assertNoReport(self.check, self.mk_pkg(cpv="dev-foo/a-b-masked-1",
            iuse="a b", required_use="a? ( !b )"))
        self.assertNoReport(self.check, self.mk_pkg(cpv="dev-foo/a-forced-1",
            iuse="a b", required_use="a? ( !b )"))
        r = self.assertReport(self.check, self.mk_pkg(cpv="dev-foo/b-forced-1",
            iuse="a b", required_use="a? ( !b )"))
        self.assertIsInstance(r, glep73.GLEP73Immutability)
        r = self.assertReports(self.check, self.mk_pkg(cpv="dev-foo/a-b-forced-1",
            iuse="a b", required_use="a? ( !b )"))
        self.assertIsInstance(r[-1], glep73.GLEP73Immutability)
        self.assertNoReport(self.check, self.mk_pkg(cpv="dev-foo/a-forced-b-masked-1",
            iuse="a b", required_use="a? ( !b )"))
        self.assertNoReport(self.check, self.mk_pkg(cpv="dev-foo/b-forced-a-masked-1",
            iuse="a b", required_use="a? ( !b )"))

    def test_conditions_can_coexist(self):
        f = glep73.GLEP73Flag
        nf = lambda x: glep73.GLEP73Flag(x, negate=True)

        self.assertTrue(glep73.conditions_can_coexist([], []))
        self.assertTrue(glep73.conditions_can_coexist([f('a')], [f('a')]))
        self.assertTrue(glep73.conditions_can_coexist(
            [f('a'), f('b'), f('c')], [f('d'), f('e'), f('f')]))
        self.assertTrue(glep73.conditions_can_coexist(
            [f('a'), f('b'), f('c')], [f('c'), nf('d'), nf('e')]))
        self.assertFalse(glep73.conditions_can_coexist(
            [f('a'), f('b'), f('c')], [nf('c'), nf('d'), nf('e')]))
        self.assertTrue(glep73.conditions_can_coexist(
            [f('a'), f('b'), f('c')], [f('a'), f('b'), f('a'), f('b'), f('a')]))
        self.assertTrue(glep73.conditions_can_coexist(
            [f('a'), f('b'), f('c')], []))
        self.assertFalse(glep73.conditions_can_coexist(
            [f('a'), f('b'), f('c')], [nf('a')]))
        self.assertFalse(glep73.conditions_can_coexist(
            [f('a'), f('b'), f('c')], [f('a'), nf('a')]))
        self.assertFalse(glep73.conditions_can_coexist(
            [f('a'), f('b'), f('c')], [f('c'), f('b'), nf('a')]))
