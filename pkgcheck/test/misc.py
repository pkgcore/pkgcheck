# Copyright: 2007 Brian Harring <ferringb@gmail.com>
# License: BSD/GPL2

from pkgcore.ebuild import eapi
from pkgcore.ebuild.atom import atom
from pkgcore.ebuild.cpv import versioned_CPV
from pkgcore.ebuild.ebuild_src import package
from pkgcore.ebuild.misc import ChunkedDataDict, split_negations, chunked_data
from pkgcore.repository.util import SimpleTree
from pkgcore.test import TestCase

from pkgcheck import base
from pkgcheck.addons import ArchesAddon

default_arches = ArchesAddon.default_arches


class FakePkg(package):
    def __init__(self, cpvstr, data=None, shared=None, parent=None):
        if data is None:
            data = {}

        for x in ("DEPEND", "RDEPEND", "PDEPEND", "IUSE", "LICENSE"):
            data.setdefault(x, "")

        cpv = versioned_CPV(cpvstr)
        package.__init__(self, shared, parent, cpv.category, cpv.package,
                         cpv.fullver)
        package.local_use = set()
        object.__setattr__(self, "data", data)

    @property
    def eapi_obj(self):
        return eapi.get_eapi(self.data.get('EAPI', '0'))


class FakeTimedPkg(package):
    __slots__ = "_mtime_"

    def __init__(self, cpvstr, mtime, data=None, shared=None, repo=None):
        if data is None:
            data = {}
        cpv = versioned_CPV(cpvstr)
        package.__init__(self, shared, repo, cpv.category, cpv.package,
                         cpv.fullver)
        object.__setattr__(self, "data", data)
        object.__setattr__(self, "_mtime_", mtime)


default_threshold_attrs = {
    base.repository_feed: (),
    base.category_feed: ('category',),
    base.package_feed: ('category', 'package'),
    base.versioned_feed: ('category', 'package', 'version'),
}
default_threshold_attrs[base.ebuild_feed] = \
    default_threshold_attrs[base.versioned_feed]


class ReportTestCase(TestCase):

    _threshold_attrs = default_threshold_attrs.copy()

    def assert_known_results(self, *reports):
        for report in reports:
            self.assertIn(report.__class__, self.check_kls.known_results)

    def assertNoReport(self, check, data, msg=""):
        l = []
        if msg:
            msg = "%s: " % msg
        r = fake_reporter(lambda r: l.append(r))
        check.feed(data, r)
        self.assert_known_results(*l)
        self.assertEqual(l, [], msg="%s%s" %
                         (msg, list(report.short_desc for report in l)))

    def assertReportSanity(self, *reports):
        for report in reports:
            attrs = self._threshold_attrs.get(report.threshold)
            self.assertTrue(attrs, msg="unknown threshold on %r" % (report.__class__,))
            for x in attrs:
                self.assertTrue(hasattr(report, x), msg="threshold %s, missing attr %s: %r %s" %
                                (report.threshold, x, report.__class__, report))

    def assertReports(self, check, data):
        l = []
        r = fake_reporter(lambda r: l.append(r))
        check.feed(data, r)
        self.assert_known_results(*l)
        self.assertTrue(l, msg="must get a report from %r %r, got none" %
                        (check, data))
        self.assertReportSanity(*l)
        return l

    def assertIsInstance(self, obj, kls):
        self.assertTrue(isinstance(obj, kls),
                        msg="%r must be %r" % (obj, kls))
        return obj

    def assertReport(self, check, data):
        r = self.assertReports(check, data)
        self.assert_known_results(*r)
        self.assertEqual(len(r), 1, msg="expected one report, got %i: %r" %
                         (len(r), r))
        self.assertReportSanity(r[0])
        return r[0]


class fake_reporter(object):
    def __init__(self, callback):
        self.add_report = callback


class Options(dict):
    __setattr__ = dict.__setitem__
    __getattr__ = dict.__getitem__
    __delattr__ = dict.__delitem__


class FakeProfile(object):

    def __init__(self, masked_use={}, stable_masked_use={}, forced_use={},
                 stable_forced_use={}, provides={}, iuse_effective=[],
                 masks=[], unmasks=[], arch='x86', name='none'):
        self.provides_repo = SimpleTree(provides)

        self.masked_use = ChunkedDataDict()
        self.masked_use.update_from_stream(
            chunked_data(atom(k), *split_negations(v))
            for k, v in masked_use.iteritems())
        self.masked_use.freeze()

        self.stable_masked_use = ChunkedDataDict()
        self.stable_masked_use.update_from_stream(
            chunked_data(atom(k), *split_negations(v))
            for k, v in stable_masked_use.iteritems())
        self.stable_masked_use.freeze()

        self.forced_use = ChunkedDataDict()
        self.forced_use.update_from_stream(
            chunked_data(atom(k), *split_negations(v))
            for k, v in forced_use.iteritems())
        self.forced_use.freeze()

        self.stable_forced_use = ChunkedDataDict()
        self.stable_forced_use.update_from_stream(
            chunked_data(atom(k), *split_negations(v))
            for k, v in stable_forced_use.iteritems())
        self.stable_forced_use.freeze()

        self.masks = tuple(map(atom, masks))
        self.unmasks = tuple(map(atom, unmasks))
        self.iuse_effective = tuple(iuse_effective)
        self.arch = arch
        self.name = name
