"""Core check classes."""

from collections import defaultdict
from functools import total_ordering

from pkgcore import fetch
from snakeoil import klass
from snakeoil.strings import pluralism

from .. import addons, base, feeds, runners, sources
from ..addons.caches import CachedAddon, CacheDisabled
from ..log import logger
from ..results import MetadataError


@total_ordering
class Check(feeds.Feed):
    """Base template for a check.

    :cvar scope: scope relative to the package repository the check runs under
    :cvar source: source of feed items
    :cvar known_results: result keywords the check can possibly yield
    """

    known_results = frozenset()
    # checkrunner class used to execute this check
    runner_cls = runners.SyncCheckRunner

    @klass.jit_attr
    def priority(self):
        """Priority that affects order in which checks are run."""
        # raise priority for checks that scan for metadata errors
        if self.known_results.intersection(MetadataError.results.values()):
            return -1
        return 0

    @property
    def source(self):
        # filter pkg feeds as required
        if self.known_results.intersection(self.options.filter):
            if self.scope >= base.version_scope:
                return (
                    sources.FilteredRepoSource,
                    (sources.LatestVersionsFilter,),
                    (("source", self._source),),
                )
            elif max(x.scope for x in self.known_results) >= base.version_scope:
                return (
                    sources.FilteredPackageRepoSource,
                    (sources.LatestPkgsFilter,),
                    (("source", self._source),),
                )
        return self._source

    def __lt__(self, other):
        if self.priority == other.priority:
            return self.__class__.__name__ < other.__class__.__name__
        return self.priority < other.priority


class RepoCheck(Check):
    """Check that requires running at a repo level."""

    runner_cls = runners.RepoCheckRunner

    def start(self):
        """Do startup here."""

    def finish(self):
        """Do cleanup and yield final results here."""
        yield from ()


class GentooRepoCheck(Check):
    """Check that is only run against the gentoo repo by default."""

    def __init__(self, *args):
        super().__init__(*args)
        if not self.options.gentoo_repo:
            check = self.__class__.__name__
            if check in self.options.selected_checks:
                self.options.override_skip["gentoo"].append(check)
            else:
                raise SkipCheck(self, "not running against gentoo repo")


class OverlayRepoCheck(Check):
    """Check that is only run against overlay repos."""

    def __init__(self, *args):
        super().__init__(*args)
        if not self.options.target_repo.masters:
            raise SkipCheck(self, "not running against overlay")


class OptionalCheck(Check):
    """Check that is only run when explicitly enabled."""


class GitCommitsCheck(OptionalCheck):
    """Check that is only run when explicitly enabled via the --commits git option."""

    runner_cls = runners.SequentialCheckRunner

    def __init__(self, *args):
        super().__init__(*args)
        if not self.options.commits:
            raise SkipCheck(self, "not scanning against git commits")


class AsyncCheck(Check):
    """Check that schedules tasks to be run asynchronously."""

    runner_cls = runners.AsyncCheckRunner

    def __init__(self, *args, results_q):
        super().__init__(*args)
        self.results_q = results_q


class NetworkCheck(AsyncCheck, OptionalCheck):
    """Check that is only run when network support is enabled."""

    required_addons = (addons.NetAddon,)

    def __init__(self, *args, net_addon, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.options.net:
            raise SkipCheck(self, "network checks not enabled")
        self.timeout = net_addon.timeout
        self.session = net_addon.session


class MirrorsCheck(Check):
    """Check that requires determining mirrors used by a given package."""

    required_addons = (addons.UseAddon,)

    def __init__(self, *args, use_addon):
        super().__init__(*args)
        self.iuse_filter = use_addon.get_filter("fetchables")

    def get_mirrors(self, pkg):
        mirrors = []
        fetchables, _ = self.iuse_filter(
            (fetch.fetchable,),
            pkg,
            pkg.generate_fetchables(allow_missing_checksums=True, ignore_unknown_mirrors=True),
        )
        for f in fetchables:
            for m in f.uri.visit_mirrors(treat_default_as_mirror=False):
                mirrors.append(m[0].mirror_name)
        return set(mirrors)


class SkipCheck(base.PkgcheckUserException):
    """Check failed to initialize due to missing dependencies or other situation.

    Checks not explicitly selected will be skipped if they raise this during
    initialization.
    """

    def __init__(self, check, msg):
        if isinstance(check, Check):
            check_name = check.__class__.__name__
        else:
            # assume the check param is a raw class object
            check_name = check.__name__
        super().__init__(f"{check_name}: {msg}")


def init_checks(enabled_addons, options, results_q, *, addons_map=None, source_map=None):
    """Initialize selected checks."""
    if addons_map is None:
        addons_map = {}
    if source_map is None:
        source_map = {}

    enabled = defaultdict(list)
    # mapping of check skip overrides
    options.override_skip = defaultdict(list)

    # initialize required caches before other addons
    enabled_addons = sorted(enabled_addons, key=lambda x: not issubclass(x, CachedAddon))

    for cls in enabled_addons:
        try:
            if issubclass(cls, AsyncCheck):
                addon = addons.init_addon(cls, options, addons_map, results_q=results_q)
            else:
                addon = addons.init_addon(cls, options, addons_map)

            if isinstance(addon, Check):
                source = source_map.get(addon.source)
                if source is None:
                    source = sources.init_source(addon.source, options, addons_map)
                    source_map[addon.source] = source
                enabled[(source, addon.runner_cls)].append(addon)
        except (CacheDisabled, SkipCheck) as e:
            # Raise exception if the related check was explicitly selected,
            # otherwise it gets transparently skipped.
            if cls.__name__ in options.selected_checks:
                if isinstance(e, SkipCheck):
                    raise
                raise SkipCheck(cls, e)

    # report which check skips were overridden
    for skip_type, checks in sorted(options.override_skip.items()):
        s = pluralism(checks)
        checks_str = ", ".join(sorted(checks))
        logger.warning(f"running {skip_type} specific check{s}: {checks_str}")

    return enabled
