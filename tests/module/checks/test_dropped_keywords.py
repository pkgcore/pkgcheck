from itertools import chain

from pkgcheck.checks import dropped_keywords

from .. import misc


class TestDroppedKeywords(misc.ReportTestCase):

    check_kls = dropped_keywords.DroppedKeywordsCheck

    def mk_pkg(self, ver, keywords='', eclasses=(), **kwargs):
        return misc.FakePkg(
            f"dev-util/diffball-{ver}",
            data={
                **kwargs,
                "KEYWORDS": keywords,
                "_eclasses_": eclasses,
            })

    def mk_check(self, arches=('x86', 'amd64'), verbosity=0):
        options = misc.Options(arches=arches, verbosity=verbosity)
        return self.check_kls(options, arches_addon=None)

    def test_it(self):
        # single version, shouldn't yield.
        check = self.mk_check()
        self.assertNoReport(check, [self.mk_pkg('1')])
        reports = self.assertReports(
            check, [self.mk_pkg("1", "x86 amd64"), self.mk_pkg("2")])
        assert set(chain.from_iterable(x.arches for x in reports)) == {"x86", "amd64"}

        # ensure it limits itself to just the arches we care about
        # check unstable at the same time;
        # finally, check '-' handling; if x86 -> -x86, that's valid.
        self.assertNoReport(
            check,
            [self.mk_pkg("1", "x86 ~amd64 ppc"),
             self.mk_pkg("2", "~amd64 x86"),
             self.mk_pkg("3", "-amd64 x86")])

        # check added keyword handling
        self.assertNoReport(
            check,
            [self.mk_pkg("1", "amd64"),
             self.mk_pkg("2", "x86"),
             self.mk_pkg("3", "~x86 ~amd64")])

        # check special keyword handling
        for key in ('-*', '*', '~*'):
            self.assertNoReport(
                check,
                [self.mk_pkg("1", "x86 ~amd64"),
                self.mk_pkg("2", key)])

        # ensure it doesn't flag live ebuilds
        self.assertNoReport(
            check,
            [self.mk_pkg("1", "x86 amd64"),
            self.mk_pkg("9999", "", PROPERTIES='live')])

    def test_verbose_mode(self):
        # verbose mode outputs a report per version with dropped keywords
        check = self.mk_check(verbosity=1)
        reports = self.assertReports(
            check,
            [self.mk_pkg("1", "x86 amd64"),
             self.mk_pkg("2"),
             self.mk_pkg("3")])
        assert len(reports) == 2
        assert {x.version for x in reports} == {"2", "3"}
        assert set(chain.from_iterable(x.arches for x in reports)) == {"x86", "amd64"}
        for r in reports:
            assert 'amd64, x86' in str(r)

    def test_regular_mode(self):
        # regular mode outputs the most recent pkg with dropped keywords
        check = self.mk_check()
        reports = self.assertReports(
            check,
            [self.mk_pkg("1", "x86 amd64"),
             self.mk_pkg("2"),
             self.mk_pkg("3")])
        assert len(reports) == 1
        assert reports[0].version == '3'
        assert set(chain.from_iterable(x.arches for x in reports)) == {"x86", "amd64"}
        assert 'amd64, x86' in str(reports[0])
