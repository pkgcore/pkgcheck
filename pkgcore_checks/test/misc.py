# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: GPL2

from pkgcore.test import TestCase
from pkgcore.ebuild.ebuild_src import package
from pkgcore.ebuild.cpv import CPV

class FakePkg(package):
    def __init__(self, cpvstr, data=None, shared=None, repo=None):
        if data is None:
            data = {}
        cpv = CPV(cpvstr)
        package.__init__(self, shared, repo, cpv.category, cpv.package,
            cpv.fullver)
        object.__setattr__(self, "data", data)


class ReportTestCase(TestCase):

    def assertNoReport(self, check, data):
        l = []
        r = fake_reporter(lambda r:l.append(r))
        check.feed(data, r)
        self.assertEqual(l, [], list(report.to_str() for report in l))

    def assertReports(self, check, data):
        l = []
        r = fake_reporter(lambda r:l.append(r))
        check.feed(data, r)
        self.assertTrue(l)
        return l

    def assertIsInstance(self, obj, kls):
        self.assertTrue(isinstance(obj, kls), 
            msg="%r must be %r" % (obj, kls))

    def assertReport(self, check, data):
        r = self.assertReports(check, data)
        self.assertEqual(len(r), 1)
        return r[0]

class fake_reporter(object):
    def __init__(self, callback):
        self.add_report = callback


class Options(dict):
    __setattr__ = dict.__setitem__
    __getattr__ = dict.__getitem__
    __delattr__ = dict.__delitem__
