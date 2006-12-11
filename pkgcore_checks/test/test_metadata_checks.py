# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: GPL2

import tempfile
from pkgcore.test.mixins import TempDirMixin
from pkgcore_checks.test import misc
from pkgcore_checks import metadata_checks
from pkgcore.util.osutils import join as pjoin


class TestDescriptionReport(misc.ReportTestCase):
    def mk_pkg(self, desc=""):
        return misc.FakePkg("dev-util/diffball-0.7.1",
            data={"DESCRIPTION":desc})

    def test_it(self):
        check = metadata_checks.DescriptionReport(None, None)
        self.assertIsInstance(self.assertReport(check, self.mk_pkg()),
            metadata_checks.CrappyDescription)
        self.assertIsInstance(self.assertReport(check,
            self.mk_pkg("based on eclass")),
            metadata_checks.CrappyDescription)
        self.assertIsInstance(self.assertReport(check,
            self.mk_pkg("diffball")),
            metadata_checks.CrappyDescription)
        self.assertIsInstance(self.assertReport(check,
            self.mk_pkg("dev-util/diffball")),
            metadata_checks.CrappyDescription)
        self.assertIsInstance(self.assertReport(check,
            self.mk_pkg("foon")),
            metadata_checks.CrappyDescription)
        self.assertIsInstance(self.assertReport(check,
            self.mk_pkg("based on eclass"*50)),
            metadata_checks.CrappyDescription)


class TestKeywordsReport(misc.ReportTestCase):
    
    def mk_pkg(self, keywords=""):
        return misc.FakePkg("dev-util/diffball-0.7.1",
            data={"KEYWORDS":keywords})

    def test_it(self):
        check = metadata_checks.KeywordsReport(None, None)
        self.assertIsInstance(self.assertReport(check, self.mk_pkg()),
            metadata_checks.EmptyKeywords)
        self.assertIsInstance(self.assertReport(check, self.mk_pkg("-*")),
            metadata_checks.StupidKeywords)


class iuse_options(TempDirMixin):

    def get_options(self, **kwds):
        repo_base = tempfile.mkdtemp(dir=self.dir)
        open(pjoin(repo_base, "arch.list"), "w").write(
            "\n".join(kwds.pop("arches", ("x86", "ppc", "amd64"))))
        
        open(pjoin(repo_base, "use.desc"), "w").write(
            "\n".join(kwds.pop("use_local_desc", ("foo", "bar"))))

        open(pjoin(repo_base, "use.local.desc"), "w").write(
            "\n".join("dev-util/diffball:%s - blah" % x for x in 
                kwds.pop("use_local_desc", ("lfoo", "lbar"))))
        
        kwds["repo_bases"] = (repo_base,)
        return misc.Options(**kwds)        


class TestIUSEMetadataReport(iuse_options, misc.ReportTestCase):

    def mk_pkg(self, iuse=""):
        return misc.FakePkg("dev-util/diffball-0.7.1",
            data={"IUSE":iuse})

    def test_it(self):
        # verify behaviour when use.* data isn't available
        check = metadata_checks.IUSEMetadataReport(
            self.get_options(), None)
        check.start()
        self.assertNoReport(check, self.mk_pkg("foo bar"))
        r = self.assertReport(check, self.mk_pkg("foo dar"))
        self.assertEqual(r.attr, "iuse")
        # arch flags must _not_ be in IUSE
        self.assertReport(check, self.mk_pkg("x86"))
        
