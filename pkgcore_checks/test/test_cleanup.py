# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: GPL2

from pkgcore_checks.test import misc
from pkgcore_checks.cleanup import RedundantVersionReport as redundant_ver

class TestRedundantVersion(misc.ReportTestCase):

    def mk_pkg(self, ver, keywords=("x86", "amd64"), slot="0"):
        return misc.FakePkg("dev-util/diffball-%s" % ver,
            data={"KEYWORDS":' '.join(keywords), "SLOT":slot})
    
    def test_it(self):
        # single version, shouldn't yield.
        check = redundant_ver(None, None)
        self.assertNoReport(check, [self.mk_pkg("0.7.1")])
        reports = self.assertReports(check, 
                [self.mk_pkg(x) for x in "0.7", "0.8", "0.9"])
        self.assertEqual([list(x.later_versions) for x in  reports], 
            [["0.9"], ["0.9", "0.8"]])
        
        # check slots.
        l = [self.mk_pkg("0.7"), self.mk_pkg("0.8", slot="1"), 
            self.mk_pkg("0.9")]
        reports = self.assertReports(check, l)
        self.assertEqual([list(x.later_versions) for x in reports],
            [["0.9"]])
