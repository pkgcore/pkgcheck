from pkgcheck.checks import python

from .. import misc


class TestPythonCheck(misc.ReportTestCase):

    check = python.PythonCheck(None)
    check_kls = python.PythonCheck

    def mk_pkg(self, cpv="app-foo/bar-1", **kwargs):
        kwargs.setdefault('EAPI', '7')
        return misc.FakePkg(cpv, data=kwargs)

    def test_multiple_eclasses(self):
        r = self.assertReport(
            self.check,
            self.mk_pkg(_eclasses_=['python-any-r1', 'python-single-r1'],
                        DEPEND='dev-lang/python'))
        assert isinstance(r, python.PythonEclassError)

    def test_missing_eclass_depend(self):
        self.assertNoReport(
            self.check,
            self.mk_pkg(_eclasses_=['python-any-r1'], DEPEND='dev-lang/python'))
        self.assertNoReport(self.check, self.mk_pkg(DEPEND='dev-foo/frobnicate'))

        r = self.assertReport(self.check, self.mk_pkg(DEPEND='dev-lang/python'))
        assert isinstance(r, python.MissingPythonEclass)
        assert 'missing python-any-r1 eclass usage for DEPEND="dev-lang/python"' in str(r)

        assert isinstance(
            self.assertReport(self.check, self.mk_pkg(DEPEND='dev-lang/python:2.7')),
            python.MissingPythonEclass)
        assert isinstance(
            self.assertReport(self.check, self.mk_pkg(DEPEND='dev-lang/python:*')),
            python.MissingPythonEclass)
        assert isinstance(
            self.assertReport(self.check, self.mk_pkg(DEPEND='=dev-lang/python-2*')),
            python.MissingPythonEclass)
        assert isinstance(
            self.assertReport(
                self.check,
                self.mk_pkg(DEPEND='|| ( dev-lang/python:2.7 dev-lang/python:3.6 )')),
            python.MissingPythonEclass)
        assert isinstance(
            self.assertReport(self.check, self.mk_pkg(DEPEND='dev-python/pypy')),
            python.MissingPythonEclass)

    def test_missing_eclass_bdepend(self):
        self.assertNoReport(
            self.check,
            self.mk_pkg(_eclasses_=['python-any-r1'], BDEPEND='dev-lang/python'))
        self.assertNoReport(self.check, self.mk_pkg(BDEPEND='dev-foo/frobnicate'))

        assert isinstance(
            self.assertReport(self.check, self.mk_pkg(BDEPEND='dev-lang/python')),
            python.MissingPythonEclass)
        assert isinstance(
            self.assertReport(self.check, self.mk_pkg(BDEPEND='dev-lang/python:2.7')),
            python.MissingPythonEclass)
        assert isinstance(
            self.assertReport(self.check, self.mk_pkg(BDEPEND='dev-lang/python:*')),
            python.MissingPythonEclass)
        assert isinstance(
            self.assertReport(self.check, self.mk_pkg(BDEPEND='=dev-lang/python-2*')),
            python.MissingPythonEclass)
        assert isinstance(
            self.assertReport(
                self.check,
                self.mk_pkg(BDEPEND='|| ( dev-lang/python:2.7 dev-lang/python:3.6 )')),
            python.MissingPythonEclass)
        assert isinstance(
            self.assertReport(self.check, self.mk_pkg(BDEPEND='dev-python/pypy')),
            python.MissingPythonEclass)

    def test_missing_eclass_rdepend(self):
        self.assertNoReport(
            self.check,
            self.mk_pkg(_eclasses_=['python-r1'], RDEPEND='dev-lang/python:2.7'))
        self.assertNoReport(
            self.check,
            self.mk_pkg(_eclasses_=['python-single-r1'], RDEPEND='dev-lang/python:2.7'))
        self.assertNoReport(self.check, self.mk_pkg(RDEPEND='dev-foo/frobnicate'))

        r = self.assertReport(self.check, self.mk_pkg(RDEPEND='dev-lang/python'))
        assert isinstance(r, python.MissingPythonEclass)
        assert 'missing python-r1 or python-single-r1 eclass' in str(r)

        assert isinstance(
            self.assertReport(self.check, self.mk_pkg(RDEPEND='dev-lang/python:2.7')),
            python.MissingPythonEclass)
        assert isinstance(
            self.assertReport(self.check, self.mk_pkg(RDEPEND='dev-lang/python:=')),
            python.MissingPythonEclass)
        assert isinstance(
            self.assertReport(self.check, self.mk_pkg(RDEPEND='=dev-lang/python-2*')),
            python.MissingPythonEclass)
        assert isinstance(
            self.assertReport(
                self.check,
                self.mk_pkg(RDEPEND='|| ( dev-lang/python:2.7 dev-lang/python:3.6 )')),
            python.MissingPythonEclass)
        assert isinstance(
            self.assertReport(self.check, self.mk_pkg(RDEPEND='dev-python/pypy')),
            python.MissingPythonEclass)

        # special exception: virtual/pypy
        self.assertNoReport(self.check, self.mk_pkg(cpv='virtual/pypy-4.1',
            RDEPEND='|| ( dev-python/pypy:0/41 dev-python/pypy-bin:0/41 )'))
        self.assertNoReport(self.check, self.mk_pkg(cpv='virtual/pypy3-4.1',
            RDEPEND='|| ( dev-python/pypy3:0/41 dev-python/pypy3-bin:0/41 )'))

    def test_missing_eclass_pdepend(self):
        self.assertNoReport(
            self.check,
            self.mk_pkg(_eclasses_=['python-r1'], PDEPEND='dev-lang/python:2.7'))
        self.assertNoReport(
            self.check,
            self.mk_pkg(_eclasses_=['python-single-r1'], PDEPEND='dev-lang/python:2.7'))
        self.assertNoReport(self.check, self.mk_pkg(PDEPEND='dev-foo/frobnicate'))

        assert isinstance(
            self.assertReport(self.check, self.mk_pkg(PDEPEND='dev-lang/python')),
            python.MissingPythonEclass)
        assert isinstance(
            self.assertReport(self.check, self.mk_pkg(PDEPEND='dev-lang/python:2.7')),
            python.MissingPythonEclass)
        assert isinstance(
            self.assertReport(self.check, self.mk_pkg(PDEPEND='dev-lang/python:=')),
            python.MissingPythonEclass)
        assert isinstance(
            self.assertReport(self.check, self.mk_pkg(PDEPEND='=dev-lang/python-2*')),
            python.MissingPythonEclass)
        assert isinstance(
            self.assertReport(
                self.check,
                self.mk_pkg(PDEPEND='|| ( dev-lang/python:2.7 dev-lang/python:3.6 )')),
            python.MissingPythonEclass)
        assert isinstance(
            self.assertReport(self.check, self.mk_pkg(PDEPEND='dev-python/pypy')),
            python.MissingPythonEclass)

    def test_valid_packages(self):
        self.assertNoReport(
            self.check,
            self.mk_pkg(
                _eclasses_=['python-r1'],
                IUSE='python_targets_python2_7 '
                     'python_targets_python3_6',
                RDEPEND='python_targets_python2_7? ( '
                        '  dev-lang/python:2.7 ) '
                        'python_targets_python3_6? ( '
                        '  dev-lang/python:3.6 )',
                REQUIRED_USE='|| ( python_targets_python2_7 '
                             '     python_targets_python3_6 )'))

        # python-single-r1 with one implementation does not use PST
        self.assertNoReport(
            self.check,
            self.mk_pkg(_eclasses_=['python-single-r1'],
                        IUSE='python_targets_python2_7',
                        RDEPEND='python_targets_python2_7? ( '
                                '  dev-lang/python:2.7 )',
                        REQUIRED_USE='python_targets_python2_7'))
        self.assertNoReport(
            self.check,
            self.mk_pkg(
                _eclasses_=['python-single-r1'],
                IUSE='python_targets_python2_7 '
                     'python_targets_python3_6 '
                     'python_single_target_python2_7 '
                     'python_single_target_python3_6',
                RDEPEND='python_single_target_python2_7? ( '
                        '  dev-lang/python:2.7 ) '
                        'python_single_target_python3_6? ( '
                        '  dev-lang/python:3.6 )',
                REQUIRED_USE='^^ ( python_single_target_python2_7 '
                             '     python_single_target_python3_6 ) '
                             'python_single_target_python2_7? ( '
                             '  python_targets_python2_7 ) '
                             'python_single_target_python3_6? ( '
                             '  python_targets_python3_6 )'))

        self.assertNoReport(
            self.check,
            self.mk_pkg(_eclasses_=['python-any-r1'],
                        DEPEND='|| ( '
                               '  dev-lang/python:2.7 '
                               '  dev-lang/python:3.6 )'))
        self.assertNoReport(
            self.check,
            self.mk_pkg(_eclasses_=['python-any-r1'], DEPEND='dev-lang/python:2.7'))
        self.assertNoReport(
            self.check,
            self.mk_pkg(_eclasses_=['python-any-r1'],
                        BDEPEND='|| ( '
                                '  dev-lang/python:2.7 '
                                '  dev-lang/python:3.6 )'))

    def test_missing_required_use(self):
        r = self.assertReport(
            self.check,
            self.mk_pkg(
                _eclasses_=['python-r1'],
                IUSE='python_targets_python2_7 '
                     'python_targets_python3_6',
                RDEPEND='python_targets_python2_7? ( '
                        '  dev-lang/python:2.7 ) '
                        'python_targets_python3_6? ( '
                        '  dev-lang/python:3.6 )'))
        assert isinstance(r, python.PythonMissingRequiredUse)
        assert 'missing REQUIRED_USE="${PYTHON_REQUIRED_USE}"' in str(r)

        # incomplete REQUIRED_USE (e.g. use of python_gen_useflags)
        assert isinstance(
            self.assertReport(
                self.check,
                self.mk_pkg(
                    _eclasses_=['python-r1'],
                    IUSE='python_targets_python2_7 '
                         'python_targets_python3_6',
                    RDEPEND='python_targets_python2_7? ( '
                            '  dev-lang/python:2.7 ) '
                            'python_targets_python3_6? ( '
                            '  dev-lang/python:3.6 )',
                    REQUIRED_USE='|| ( python_targets_python2_7 )')),
            python.PythonMissingRequiredUse)

        assert isinstance(
            self.assertReport(
                self.check,
                self.mk_pkg(
                    _eclasses_=['python-r1'],
                    IUSE='python_targets_python2_7 '
                         'python_targets_python3_6 '
                         'python_targets_python3_7',
                    RDEPEND='python_targets_python2_7? ( '
                            '  dev-lang/python:2.7 ) '
                            'python_targets_python3_6? ( '
                            '  dev-lang/python:3.6 ) '
                            'python_targets_python3_7? ( '
                            '  dev-lang/python:3.7 )',
                    REQUIRED_USE='|| ( python_targets_python3_6 '
                                 '  python_targets_python3_7 )')),
            python.PythonMissingRequiredUse)

        assert isinstance(
            self.assertReport(
                self.check,
                self.mk_pkg(
                    _eclasses_=['python-single-r1'],
                    IUSE='python_targets_python2_7 '
                         'python_targets_python3_6 '
                         'python_single_target_python2_7 '
                         'python_single_target_python3_6',
                    RDEPEND='python_single_target_python2_7? ( '
                            '  dev-lang/python:2.7 ) '
                            'python_single_target_python3_6? ( '
                            '  dev-lang/python:3.6 )')),
            python.PythonMissingRequiredUse)

        # incomplete REQUIRED_USE
        assert isinstance(
            self.assertReport(
                self.check,
                self.mk_pkg(
                    _eclasses_=['python-single-r1'],
                    IUSE='python_targets_python2_7 '
                         'python_targets_python3_6 '
                         'python_single_target_python2_7 '
                         'python_single_target_python3_6',
                    RDEPEND='python_single_target_python2_7? ( '
                            '  dev-lang/python:2.7 ) '
                            'python_single_target_python3_6? ( '
                            '  dev-lang/python:3.6 )',
                    REQUIRED_USE='^^ ( python_single_target_python2_7 )')),
            python.PythonMissingRequiredUse)

        # || instead of ^^ in python-single-r1
        assert isinstance(
            self.assertReport(
                self.check,
                self.mk_pkg(
                    _eclasses_=['python-single-r1'],
                    IUSE='python_targets_python2_7 '
                         'python_targets_python3_6 '
                         'python_single_target_python2_7 '
                         'python_single_target_python3_6',
                    RDEPEND='python_single_target_python2_7? ( '
                            '  dev-lang/python:2.7 ) '
                            'python_single_target_python3_6? ( '
                            '  dev-lang/python:3.6 )',
                    REQUIRED_USE='|| ( python_targets_python2_7 '
                                 '  python_targets_python3_6 )')),
            python.PythonMissingRequiredUse)

    def test_missing_deps(self):
        r = self.assertReport(
            self.check,
            self.mk_pkg(
                _eclasses_=['python-r1'],
                IUSE='python_targets_python2_7 '
                     'python_targets_python3_6',
                REQUIRED_USE='|| ( python_targets_python2_7 '
                             '     python_targets_python3_6 )'))
        assert isinstance(r, python.PythonMissingDeps)
        assert 'missing RDEPEND="${PYTHON_DEPS}"' in str(r)

        # incomplete deps
        r = self.assertReport(
            self.check,
            self.mk_pkg(
                _eclasses_=['python-r1'],
                IUSE='python_targets_python2_7 '
                     'python_targets_python3_6',
                RDEPEND='python_targets_python2_7? ( '
                        '  dev-lang/python:2.7 )',
                REQUIRED_USE='|| ( python_targets_python2_7 '
                             '     python_targets_python3_6 )'))
        assert isinstance(r, python.PythonMissingDeps)
        assert 'missing RDEPEND="${PYTHON_DEPS}"' in str(r)

        # check that irrelevant dep with same USE conditional does not wrongly
        # satisfy the check
        assert isinstance(
            self.assertReport(
                self.check,
                self.mk_pkg(
                    _eclasses_=['python-r1'],
                    IUSE='python_targets_python2_7 '
                         'python_targets_python3_6',
                    RDEPEND='python_targets_python2_7? ( '
                            '  dev-foo/bar ) '
                            'python_targets_python3_6? ( '
                            '  dev-lang/python:3.6 )',
                    REQUIRED_USE='|| ( python_targets_python2_7 '
                                 '     python_targets_python3_6 )')),
            python.PythonMissingDeps)

        # DEPEND only, RDEPEND missing
        assert isinstance(
            self.assertReport(
                self.check,
                self.mk_pkg(
                    _eclasses_=['python-r1'],
                    IUSE='python_targets_python2_7 '
                         'python_targets_python3_6',
                    DEPEND='python_targets_python2_7? ( '
                           '  dev-lang/python:2.7 ) '
                           'python_targets_python3_6? ( '
                           '  dev-lang/python:3.6 )',
                    REQUIRED_USE='|| ( python_targets_python2_7 '
                                 '     python_targets_python3_6 )')),
            python.PythonMissingDeps)

        assert isinstance(
            self.assertReport(
                self.check,
                self.mk_pkg(
                    _eclasses_=['python-single-r1'],
                    IUSE='python_targets_python2_7 '
                         'python_targets_python3_6 '
                         'python_single_target_python2_7 '
                         'python_single_target_python3_6',
                    REQUIRED_USE='^^ ( python_single_target_python2_7 '
                                 '     python_single_target_python3_6 ) '
                                 'python_single_target_python2_7? ( '
                                 '  python_targets_python2_7 ) '
                                 'python_single_target_python3_6? ( '
                                 '  python_targets_python3_6 )')),
            python.PythonMissingDeps)

        # incomplete deps
        assert isinstance(
            self.assertReport(
                self.check,
                self.mk_pkg(
                    _eclasses_=['python-single-r1'],
                    IUSE='python_targets_python2_7 '
                         'python_targets_python3_6 '
                         'python_single_target_python2_7 '
                         'python_single_target_python3_6',
                    RDEPEND='python_single_target_python2_7? ( '
                            '  dev-lang/python:2.7 )',
                    REQUIRED_USE='^^ ( python_single_target_python2_7 '
                                 '     python_single_target_python3_6 ) '
                                 'python_single_target_python2_7? ( '
                                 '  python_targets_python2_7 ) '
                                 'python_single_target_python3_6? ( '
                                 '  python_targets_python3_6 )')),
            python.PythonMissingDeps)

        # check that irrelevant dep with same USE conditional does not wrongly
        # satisfy the check
        assert isinstance(
            self.assertReport(
                self.check,
                self.mk_pkg(
                    _eclasses_=['python-single-r1'],
                    IUSE='python_targets_python2_7 '
                         'python_targets_python3_6 '
                         'python_single_target_python2_7 '
                         'python_single_target_python3_6',
                    RDEPEND='python_single_target_python2_7? ( '
                            '  dev-foo/bar ) '
                            'python_single_target_python3_6? ( '
                            '  dev-lang/python:3.6 )',
                    REQUIRED_USE='^^ ( python_single_target_python2_7 '
                                 '     python_single_target_python3_6 ) '
                                 'python_single_target_python2_7? ( '
                                 '  python_targets_python2_7 ) '
                                 'python_single_target_python3_6? ( '
                                 '  python_targets_python3_6 )')),
            python.PythonMissingDeps)

        # DEPEND only, RDEPEND missing
        assert isinstance(
            self.assertReport(
                self.check,
                self.mk_pkg(
                    _eclasses_=['python-single-r1'],
                    IUSE='python_targets_python2_7 '
                         'python_targets_python3_6 '
                         'python_single_target_python2_7 '
                         'python_single_target_python3_6',
                    DEPEND='python_single_target_python2_7? ( '
                           '  dev-lang/python:2.7 ) '
                           'python_single_target_python3_6? ( '
                           '  dev-lang/python:3.6 )',
                    REQUIRED_USE='^^ ( python_single_target_python2_7 '
                                 '     python_single_target_python3_6 ) '
                                 'python_single_target_python2_7? ( '
                                 '  python_targets_python2_7 ) '
                                 'python_single_target_python3_6? ( '
                                 '  python_targets_python3_6 )')),
            python.PythonMissingDeps)

        # check that the check isn't wrongly satisfied by PYTHON_TARGETS
        # in python-single-r1 (PYTHON_SINGLE_TARGET expected)
        assert isinstance(
            self.assertReport(
                self.check,
                self.mk_pkg(
                    _eclasses_=['python-single-r1'],
                    IUSE='python_targets_python2_7 '
                         'python_targets_python3_6 '
                         'python_single_target_python2_7 '
                         'python_single_target_python3_6',
                    RDEPEND='python_targets_python2_7? ( '
                            '  dev-lang/python:2.7 ) '
                            'python_targets_python3_6? ( '
                            '  dev-lang/python:3.6 )',
                    REQUIRED_USE='^^ ( python_single_target_python2_7 '
                                 '     python_single_target_python3_6 ) '
                                 'python_single_target_python2_7? ( '
                                 '  python_targets_python2_7 ) '
                                 'python_single_target_python3_6? ( '
                                 '  python_targets_python3_6 )')),
            python.PythonMissingDeps)

        assert isinstance(
            self.assertReport(self.check, self.mk_pkg(_eclasses_=['python-any-r1'])),
            python.PythonMissingDeps)

    def test_runtime_dep_in_any_r1(self):
        r = self.assertReport(
            self.check,
            self.mk_pkg(
                _eclasses_=['python-any-r1'],
                DEPEND='|| ( '
                       '  dev-lang/python:2.7 '
                       '  dev-lang/python:3.6 )',
                RDEPEND='|| ( '
                        '  dev-lang/python:2.7 '
                        '  dev-lang/python:3.6 )'))
        assert isinstance(r, python.PythonRuntimeDepInAnyR1)
        assert 'inherits python-any-r1 with RDEPEND="dev-lang/python:2.7"' in str(r)

        # shouldn't trigger for blockers
        self.assertNoReport(
            self.check,
            self.mk_pkg(
                _eclasses_=['python-any-r1'],
                DEPEND='dev-lang/python:2.7',
                RDEPEND='!dev-python/pypy3-bin:0'))
