import multiprocessing
import random
import string
from dataclasses import dataclass
from typing import List

import pytest
from pkgcheck import addons, base, sources
from pkgcheck.addons.caches import CachedAddon, CacheDisabled
from pkgcheck.checks import AsyncCheck, SkipCheck
from pkgcore.ebuild import domain, repo_objs
from pkgcore.ebuild.atom import atom
from pkgcore.ebuild.cpv import VersionedCPV
from pkgcore.ebuild.eapi import get_eapi
from pkgcore.ebuild.ebuild_src import package
from pkgcore.ebuild.misc import ChunkedDataDict, chunked_data
from pkgcore.package.metadata import factory
from pkgcore.repository import prototype
from pkgcore.repository.util import SimpleTree
from snakeoil.cli import arghparse
from snakeoil.data_source import text_data_source
from snakeoil.osutils import pjoin
from snakeoil.sequences import split_negations


@dataclass
class Profile:
    """Profile record used to create profiles in a repository."""

    path: str
    arch: str
    status: str = "stable"
    deprecated: bool = False
    defaults: List[str] = None
    eapi: str = "5"


# TODO: merge this with the pkgcore-provided equivalent
class FakePkg(package):
    def __init__(self, cpvstr, data=None, parent=None, ebuild="", **kwargs):
        if data is None:
            data = {}

        for x in ("DEPEND", "RDEPEND", "PDEPEND", "IUSE", "LICENSE"):
            data.setdefault(x, "")

        cpv = VersionedCPV(cpvstr)
        # TODO: make pkgcore generate empty shared pkg data when None is passed
        mxml = repo_objs.LocalMetadataXml("")
        shared = repo_objs.SharedPkgData(metadata_xml=mxml, manifest=None)
        super().__init__(shared, parent, cpv.category, cpv.package, cpv.fullver)
        object.__setattr__(self, "data", data)
        object.__setattr__(self, "_ebuild", ebuild)

        # custom attributes
        for attr, value in kwargs.items():
            object.__setattr__(self, attr, value)

    @property
    def eapi(self):
        return get_eapi(self.data.get("EAPI", "0"))

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
        object.__setattr__(
            self,
            "path",
            pjoin(repo.location, cpv.category, cpv.package, f"{cpv.package}-{cpv.fullver}.ebuild"),
        )


class ReportTestCase:
    """Base class for verifying report generation."""

    def _assertReportSanity(self, *reports):
        for report in reports:
            assert report.__class__ in self.check_kls.known_results
            # pull desc to force a render for basic sanity checks
            assert report.desc

    def _run_check(self, check, data):
        if isinstance(data, sources.Source):
            source = data
            options = source.options
        elif isinstance(data, prototype.tree):
            options = arghparse.Namespace(target_repo=data)
            source = sources.RepoSource(options)
        else:
            if not isinstance(data, tuple):
                data = [data]
            options = arghparse.Namespace()
            source = sources.Source(options, data)

        results = []
        runner = check.runner_cls(options, source, [check])
        results.extend(runner.run())
        return results

    def assertNoReport(self, check, data, msg=""):
        if msg:
            msg = f"{msg}: "
        results = self._run_check(check, data)
        assert results == [], f"{msg}{list(report.desc for report in results)}"

    def assertReports(self, check, data):
        results = self._run_check(check, data)
        assert results, f"must get a report from {check} {data}, got none"
        self._assertReportSanity(*results)
        return results

    def assertReport(self, check, data):
        results = self.assertReports(check, data)
        results_str = "\n".join(map(str, results))
        assert len(results) == 1, f"expected one report, got {len(results)}:\n{results_str}"
        self._assertReportSanity(*results)
        result = results[0]
        return result


class FakeProfile:
    def __init__(
        self,
        masked_use={},
        stable_masked_use={},
        forced_use={},
        stable_forced_use={},
        pkg_use={},
        provides={},
        iuse_effective=[],
        use=[],
        masks=[],
        unmasks=[],
        arch="x86",
        name="none",
    ):
        self.provides_repo = SimpleTree(provides)

        self.masked_use = ChunkedDataDict()
        self.masked_use.update_from_stream(
            chunked_data(atom(k), *split_negations(v)) for k, v in masked_use.items()
        )
        self.masked_use.freeze()

        self.stable_masked_use = ChunkedDataDict()
        self.stable_masked_use.update_from_stream(
            chunked_data(atom(k), *split_negations(v)) for k, v in stable_masked_use.items()
        )
        self.stable_masked_use.freeze()

        self.forced_use = ChunkedDataDict()
        self.forced_use.update_from_stream(
            chunked_data(atom(k), *split_negations(v)) for k, v in forced_use.items()
        )
        self.forced_use.freeze()

        self.stable_forced_use = ChunkedDataDict()
        self.stable_forced_use.update_from_stream(
            chunked_data(atom(k), *split_negations(v)) for k, v in stable_forced_use.items()
        )
        self.stable_forced_use.freeze()

        self.pkg_use = ChunkedDataDict()
        self.pkg_use.update_from_stream(
            chunked_data(atom(k), *split_negations(v)) for k, v in pkg_use.items()
        )
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
class Tmpdir:
    """Provide access to a temporary directory across all test methods."""

    @pytest.fixture(autouse=True)
    def _create_tmpdir(self, tmpdir):
        self.dir = str(tmpdir)


def random_str(length=10):
    """Generate a random string of ASCII characters of a given length."""
    return "".join(random.choice(string.ascii_letters) for _ in range(length))


# TODO: combine this with pkgcheck.checks.init_checks()
def init_check(check_cls, options):
    """Initialize an individual check."""
    addons_map = {}
    enabled_addons = base.get_addons([check_cls])
    results_q = multiprocessing.SimpleQueue()

    # initialize required caches before other addons
    enabled_addons = sorted(enabled_addons, key=lambda x: not issubclass(x, CachedAddon))

    # check class is guaranteed to be last in the list
    try:
        for cls in enabled_addons:
            if issubclass(cls, AsyncCheck):
                addon = addons.init_addon(cls, options, addons_map, results_q=results_q)
            else:
                addon = addons.init_addon(cls, options, addons_map)

        source = sources.init_source(addon.source, options, addons_map)
    except CacheDisabled as e:
        raise SkipCheck(cls, e)

    required_addons = {base.param_name(x): addons_map[x] for x in addon.required_addons}
    return addon, required_addons, source
