# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: BSD/GPL2

from pkgcore_checks.test import misc
from pkgcore_checks.dropped_keywords import DroppedKeywordsReport as drop_keys

class TestDroppedKeywords(misc.ReportTestCase):

    check_kls = drop_keys

    def mk_pkg(self, ver, keywords=''):
        return misc.FakePkg("dev-util/diffball-%s" % ver,
            data={"KEYWORDS":keywords})

    def test_it(self):
        # single version, shouldn't yield.
        check = drop_keys(misc.Options((("arches", ["x86", "amd64"]),)))
        self.assertNoReport(check, [self.mk_pkg('1')])
        reports = self.assertReports(check,
            [self.mk_pkg("1", "x86 amd64"), self.mk_pkg("2")])
        self.assertEqual(set(x.arch for x in reports), set(["x86", "amd64"]))

        # ensure it limits it's self to just the arches we care about
        # check unstable at the same time;
        # finally, check '-' handling; if x86 -> -x86, that's valid.
        self.assertNoReport(check,
            [self.mk_pkg("1", "x86 ~amd64 ppc"),
                self.mk_pkg("2", "~amd64 x86"),
                self.mk_pkg("3", "-amd64 x86")])

