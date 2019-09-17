from itertools import chain
import os
import textwrap

import pytest

from pkgcore import const as pkgcore_const
from pkgcore.util.commandline import Tool
from pkgcore.ebuild import domain, repo_objs
from pkgcore.ebuild.atom import atom
from pkgcore.ebuild.cpv import VersionedCPV
from pkgcore.ebuild.eapi import get_eapi
from pkgcore.ebuild.ebuild_src import package
from pkgcore.ebuild.misc import ChunkedDataDict, chunked_data
from pkgcore.package.metadata import factory
from pkgcore.repository.util import SimpleTree
from snakeoil.data_source import text_data_source
from snakeoil.mappings import ImmutableDict
from snakeoil.osutils import pjoin
from snakeoil.sequences import split_negations

from pkgcheck import base
from pkgcheck.scripts import pkgcheck


# TODO: merge this with the pkgcore-provided equivalent
class FakePkg(package):

    def __init__(self, cpvstr, data=None, parent=None, ebuild=''):
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


default_threshold_attrs = {
    base.repository_feed: (),
    base.category_feed: ('category',),
    base.package_feed: ('category', 'package'),
    base.versioned_feed: ('category', 'package', 'version'),
}
default_threshold_attrs[base.ebuild_feed] = default_threshold_attrs[base.versioned_feed]


class ReportTestCase(object):
    """Base class for verifying report generation."""

    _threshold_attrs = default_threshold_attrs.copy()

    def _assert_known_results(self, *reports):
        for report in reports:
            assert report.__class__ in self.check_kls.known_results

    def assertNoReport(self, check, data, msg="", iterate=False):
        l = []
        if msg:
            msg = f"{msg}: "
        runner = base.CheckRunner([check])
        l.extend(runner.start())
        if iterate:
            reports = chain.from_iterable(runner.feed(item) for item in data)
        else:
            reports = runner.feed(data)
        l.extend(reports)
        l.extend(runner.finish())
        self._assert_known_results(*l)
        assert l == [], f"{msg}{list(report.desc for report in l)}"

    def assertReportSanity(self, *reports):
        for report in reports:
            attrs = self._threshold_attrs.get(report.threshold)
            for attr in attrs:
                assert hasattr(report, attr), (
                    f"threshold {report.threshold}, missing attr {attr}: " \
                    f"{report.__class__!r} {report}")

    def assertReports(self, check, data, iterate=False):
        l = []
        runner = base.CheckRunner([check])
        l.extend(runner.start())
        if iterate:
            reports = chain.from_iterable(runner.feed(item) for item in data)
        else:
            reports = runner.feed(data)
        l.extend(reports)
        l.extend(runner.finish())
        self._assert_known_results(*l)
        assert l, f"must get a report from {check} {data}, got none"
        self.assertReportSanity(*l)
        return l

    def assertReport(self, check, data, iterate=False):
        r = self.assertReports(check, data, iterate=iterate)
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


@pytest.fixture(scope="session")
def fakeconfig(tmp_path_factory):
    """Generate a portage config that sets the default repo to pkgcore's stubrepo."""
    fakeconfig = tmp_path_factory.mktemp('fakeconfig')
    repos_conf = fakeconfig / 'repos.conf'
    stubrepo = pjoin(pkgcore_const.DATA_PATH, 'stubrepo')
    with open(repos_conf, 'w') as f:
        f.write(textwrap.dedent(f"""\
            [DEFAULT]
            main-repo = stubrepo

            [stubrepo]
            location = {stubrepo}
        """))
    return str(fakeconfig)


@pytest.fixture(scope="session")
def testconfig(tmp_path_factory):
    """Generate a portage config that sets the default repo to pkgcore's stubrepo.

    Also, repo entries for all the bundled test repos.
    """
    testconfig = tmp_path_factory.mktemp('testconfig')
    repos_conf = testconfig / 'repos.conf'
    stubrepo = pjoin(pkgcore_const.DATA_PATH, 'stubrepo')
    testdir = pjoin(os.path.dirname(os.path.dirname(__file__)), 'repos')
    with open(repos_conf, 'w') as f:
        f.write(textwrap.dedent(f"""\
            [DEFAULT]
            main-repo = stubrepo

            [stubrepo]
            location = {stubrepo}
            [overlayed]
            location = {pjoin(testdir, 'overlayed')}
        """))
    return str(testconfig)


@pytest.fixture(scope="session")
def cache_dir(tmp_path_factory):
    """Generate a cache directory for pkgcheck."""
    cache_dir = tmp_path_factory.mktemp('cache')
    return str(cache_dir)


@pytest.fixture
def fakerepo(tmp_path):
    """Generate a stub repo."""
    fakerepo = str(tmp_path)
    os.makedirs(pjoin(fakerepo, 'profiles'))
    os.makedirs(pjoin(fakerepo, 'metadata'))
    with open(pjoin(fakerepo, 'profiles', 'repo_name'), 'w') as f:
        f.write('fakerepo\n')
    with open(pjoin(fakerepo, 'metadata', 'layout.conf'), 'w') as f:
        f.write('masters =\n')
    return fakerepo


@pytest.fixture(scope="session")
def tool(fakeconfig):
    """Generate a tool utility for running pkgcheck."""
    tool = Tool(pkgcheck.argparser)
    tool.parser.set_defaults(override_config=fakeconfig)
    return tool
