import pytest

from pkgcore.ebuild import domain, repo_objs
from pkgcore.ebuild.atom import atom
from pkgcore.ebuild.cpv import VersionedCPV
from pkgcore.ebuild.eapi import get_eapi
from pkgcore.ebuild.ebuild_src import package
from pkgcore.ebuild.misc import ChunkedDataDict, chunked_data
from pkgcore.package.metadata import factory
from pkgcore.repository import prototype
from pkgcore.repository.util import SimpleTree
from snakeoil.data_source import text_data_source
from snakeoil.mappings import ImmutableDict
from snakeoil.osutils import pjoin
from snakeoil.sequences import split_negations

from pkgcheck import base, pipeline


# TODO: merge this with the pkgcore-provided equivalent
class FakePkg(package):

    def __init__(self, cpvstr, data=None, parent=None, ebuild='', **kwargs):
        if data is None:
            data = {}

        for x in ("DEPEND", "RDEPEND", "PDEPEND", "IUSE", "LICENSE"):
            data.setdefault(x, "")

        cpv = VersionedCPV(cpvstr)
        # TODO: make pkgcore generate empty shared pkg data when None is passed
        mxml = repo_objs.LocalMetadataXml('')
        shared = repo_objs.SharedPkgData(metadata_xml=mxml, manifest=None)
        super().__init__(shared, parent, cpv.category, cpv.package, cpv.fullver)
        object.__setattr__(self, "data", data)
        object.__setattr__(self, "_ebuild", ebuild)

        # custom attributes
        for attr, value in kwargs.items():
            object.__setattr__(self, attr, value)

    @property
    def eapi(self):
        return get_eapi(self.data.get('EAPI', '0'))

    @property
    def ebuild(self):
        return text_data_source(self._ebuild)


class FakeTimedPkg(package):

    __slots__ = "_mtime_"

    def __init__(self, cpvstr, mtime, data=None, shared=None, repo=None):
        if data is None:
            data = {}
        cpv = VersionedCPV(cpvstr)
        super().__init__(shared, factory(repo), cpv.category, cpv.package, cpv.fullver)
        object.__setattr__(self, "data", data)
        object.__setattr__(self, "_mtime_", mtime)


class FakeFilesDirPkg(package):

    __slots__ = ("path",)

    def __init__(self, cpvstr, repo, data=None, shared=None):
        if data is None:
            data = {}
        cpv = VersionedCPV(cpvstr)
        super().__init__(shared, factory(repo), cpv.category, cpv.package, cpv.fullver)
        object.__setattr__(self, "data", data)
        object.__setattr__(self, "path", pjoin(
            repo.location, cpv.category, cpv.package, f'{cpv.package}-{cpv.fullver}.ebuild'))


default_scope_attrs = {
    base.repository_scope: (),
    base.category_scope: ('category',),
    base.package_scope: ('category', 'package'),
    base.version_scope: ('category', 'package', 'version'),
}


class ReportTestCase(object):
    """Base class for verifying report generation."""

    _scope_attrs = default_scope_attrs.copy()

    def _assert_known_results(self, *reports):
        for report in reports:
            assert report.__class__ in self.check_kls.known_results

    def assertNoReport(self, check, data, msg=""):
        l = []
        if msg:
            msg = f"{msg}: "
        if isinstance(data, (prototype.tree, tuple)):
            source = data
        else:
            source = [data]
        runner = pipeline.CheckRunner(Options(), source, [check])
        runner.start()
        l.extend(runner.run())
        l.extend(runner.finish())
        self._assert_known_results(*l)
        assert l == [], f"{msg}{list(report.desc for report in l)}"

    def assertReportSanity(self, *reports):
        for report in reports:
            attrs = self._scope_attrs.get(report.scope)
            for attr in attrs:
                assert hasattr(report, attr), (
                    f"missing attr {attr}: {report.__class__!r} {report}")

    def assertReports(self, check, data):
        l = []
        if isinstance(data, (prototype.tree, tuple)):
            source = data
        else:
            source = [data]
        runner = pipeline.CheckRunner(Options(), source, [check])
        runner.start()
        l.extend(runner.run())
        l.extend(runner.finish())
        self._assert_known_results(*l)
        assert l, f"must get a report from {check} {data}, got none"
        self.assertReportSanity(*l)
        return l

    def assertReport(self, check, data):
        r = self.assertReports(check, data)
        self._assert_known_results(*r)
        assert len(r) == 1, f"expected one report, got {len(r)}: {r}"
        self.assertReportSanity(r[0])
        return r[0]


class Options(dict):
    __setattr__ = dict.__setitem__
    __getattr__ = dict.__getitem__
    __delattr__ = dict.__delitem__


class FakeProfile(object):

    def __init__(self, masked_use={}, stable_masked_use={}, forced_use={},
                 stable_forced_use={}, pkg_use={}, provides={}, iuse_effective=[],
                 use=[], masks=[], unmasks=[], arch='x86', name='none'):
        self.provides_repo = SimpleTree(provides)

        self.masked_use = ChunkedDataDict()
        self.masked_use.update_from_stream(
            chunked_data(atom(k), *split_negations(v))
            for k, v in masked_use.items())
        self.masked_use.freeze()

        self.stable_masked_use = ChunkedDataDict()
        self.stable_masked_use.update_from_stream(
            chunked_data(atom(k), *split_negations(v))
            for k, v in stable_masked_use.items())
        self.stable_masked_use.freeze()

        self.forced_use = ChunkedDataDict()
        self.forced_use.update_from_stream(
            chunked_data(atom(k), *split_negations(v))
            for k, v in forced_use.items())
        self.forced_use.freeze()

        self.stable_forced_use = ChunkedDataDict()
        self.stable_forced_use.update_from_stream(
            chunked_data(atom(k), *split_negations(v))
            for k, v in stable_forced_use.items())
        self.stable_forced_use.freeze()

        self.pkg_use = ChunkedDataDict()
        self.pkg_use.update_from_stream(
            chunked_data(atom(k), *split_negations(v))
            for k, v in pkg_use.items())
        self.pkg_use.freeze()

        self.masks = tuple(map(atom, masks))
        self.unmasks = tuple(map(atom, unmasks))
        self.iuse_effective = set(iuse_effective)
        self.use = set(use)
        self.key = arch
        self.name = name

        vfilter = domain.generate_filter(self.masks, self.unmasks)
        self.visible = vfilter.match


# TODO: move to snakeoil.test or somewhere more generic
class Tmpdir(object):
    """Provide access to a temporary directory across all test methods."""

    @pytest.fixture(autouse=True)
    def _create_tmpdir(self, tmpdir):
        self.dir = str(tmpdir)
