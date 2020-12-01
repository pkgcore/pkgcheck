"""Core check classes."""

from collections import defaultdict
from functools import total_ordering

from snakeoil import klass
from snakeoil.cli.exceptions import UserException

from .. import addons, base, feeds, sources
from ..caches import CachedAddon
from ..results import FilteredVersionResult, MetadataError


@total_ordering
class Check(feeds.Feed):
    """Base template for a check.

    :cvar scope: scope relative to the package repository the check runs under
    :cvar source: source of feed items
    :cvar known_results: result keywords the check can possibly yield
    """

    # check priority that affects runtime ordering
    _priority = 0
    # flag to allow package feed filtering
    _filtering = True
    known_results = frozenset()

    @klass.jit_attr
    def priority(self):
        """Priority that affects order in which checks are run."""
        # raise priority for checks that scan for metadata errors
        if self._priority == 0 and self.known_results & MetadataError.results:
            return -1
        return self._priority

    @property
    def source(self):
        # replace versioned pkg feeds with filtered ones as required
        if self._filtering and self.options.verbosity < 1 and self.scope is base.version_scope:
            filtered_results = [
                x for x in self.known_results if issubclass(x, FilteredVersionResult)]
            if filtered_results:
                partial_filtered = len(filtered_results) != len(self.known_results)
                return (
                    sources.FilteredRepoSource,
                    (sources.LatestPkgsFilter, partial_filtered),
                    (('source', self._source),)
                )
        return self._source

    def start(self):
        """Do startup here."""

    def finish(self):
        """Do cleanup and yield final results here."""
        yield from ()

    def __lt__(self, other):
        if self.priority == other.priority:
            return self.__class__.__name__ < other.__class__.__name__
        return self.priority < other.priority


class GentooRepoCheck(Check):
    """Check that is only run against the gentoo repo."""

    def __init__(self, *args):
        super().__init__(*args)
        if not self.options.gentoo_repo:
            raise SkipCheck(self, 'not running against gentoo repo')


class OverlayRepoCheck(Check):
    """Check that is only run against overlay repos."""

    def __init__(self, *args):
        super().__init__(*args)
        if not self.options.target_repo.masters:
            raise SkipCheck(self, 'not running against overlay')


class OptionalCheck(Check):
    """Check that is only run when explicitly enabled."""


class GitCheck(OptionalCheck):
    """Check that is only run when explicitly enabled via the --commits git option."""

    def __init__(self, *args):
        super().__init__(*args)
        if not self.options.commits:
            raise SkipCheck(self, 'not scanning against git commits')


class GitCacheCheck(Check):
    """Check that requires the git cache."""

    def __init__(self, *args):
        super().__init__(*args)
        if not self.options.cache['git']:
            raise SkipCheck(self, 'git cache support required')


class EclassCacheCheck(Check):
    """Check that requires the eclass cache."""

    def __init__(self, *args):
        super().__init__(*args)
        if not self.options.cache['eclass']:
            raise SkipCheck(self, 'eclass cache support required')


class AsyncCheck(Check):
    """Check that schedules tasks to be run asynchronously."""

    def __init__(self, *args):
        super().__init__(*args)
        # TODO: raise SkipCheck here when results_q is missing
        self._results_q = getattr(self.options, '_results_q', None)


class NetworkCheck(AsyncCheck, OptionalCheck):
    """Check that is only run when network support is enabled."""

    required_addons = (addons.NetAddon,)

    def __init__(self, *args, net_addon):
        super().__init__(*args)
        if not self.options.net:
            raise SkipCheck(self, 'network checks not enabled')
        self.timeout = self.options.timeout
        self.session = net_addon.session


class SkipCheck(UserException):
    """Check failed to initialize due to missing dependencies or other situation.

    Checks not explicitly selected will be skipped if they raise this during
    initialization.
    """

    def __init__(self, check, msg):
        check_name = check.__class__.__name__
        super().__init__(f'{check_name}: {msg}')


def init_checks(enabled_addons, options):
    """Initialize selected checks."""
    enabled = defaultdict(list)
    addons_map = {}
    source_map = {}

    # initialize required caches before other addons
    enabled_addons = sorted(enabled_addons, key=lambda x: not issubclass(x, CachedAddon))

    for cls in enabled_addons:
        try:
            addon = addons.init_addon(cls, options, addons_map)
        except SkipCheck:
            if cls.__name__ in options.selected_checks:
                raise
            continue
        if isinstance(addon, Check):
            source = source_map.get(addon.source)
            if source is None:
                source = sources.init_source(addon.source, options, addons_map)
                source_map[addon.source] = source
            exec_type = 'async' if isinstance(addon, AsyncCheck) else 'sync'
            enabled[(source, exec_type)].append(addon)

    return enabled
