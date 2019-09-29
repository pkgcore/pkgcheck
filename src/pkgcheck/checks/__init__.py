"""Core check classes."""

from .. import base, feeds, sources
from ..log import logger


class Check(feeds.Feed):
    """Base template for a check.

    :cvar scope: scope relative to the package repository the check runs under
    :cvar source: source of feed items
    :cvar known_results: result keywords the check can possibly yield
    """

    known_results = ()

    @property
    def source(self):
        # replace versioned pkg feeds with filtered ones as required
        if self.options.verbosity < 1 and self.scope == base.version_scope:
            filtered_results = [
                x for x in self.known_results if issubclass(x, base.FilteredVersionResult)]
            if filtered_results:
                partial_filtered = len(filtered_results) != len(self.known_results)
                return (
                    sources.FilteredRepoSource,
                    (sources.LatestPkgsFilter, partial_filtered),
                    (('source', self._source),)
                )
        return self._source

    @classmethod
    def skip(cls, namespace):
        """Conditionally skip check when running all enabled checks."""
        return False


class GentooRepoCheck(Check):
    """Check that is only run against the gentoo repo."""

    @classmethod
    def skip(cls, namespace):
        skip = not namespace.gentoo_repo
        if skip:
            logger.info(f'skipping {cls.__name__}, not running against gentoo repo')
        return skip or super().skip(namespace)


class OverlayRepoCheck(Check):
    """Check that is only run against overlay repos."""

    @classmethod
    def skip(cls, namespace):
        skip = not namespace.target_repo.masters
        if skip:
            logger.info(f'skipping {cls.__name__}, not running against overlay repo')
        return skip or super().skip(namespace)


class ExplicitlyEnabledCheck(Check):
    """Check that is only run when explicitly enabled."""

    @classmethod
    def skip(cls, namespace):
        if namespace.selected_checks is not None:
            disabled, enabled = namespace.selected_checks
        else:
            disabled, enabled = [], []

        # enable checks for selected keywords
        keywords = namespace.filtered_keywords
        if keywords is not None:
            keywords = keywords.intersection(cls.known_results)

        enabled += namespace.forced_checks
        skip = cls.__name__ not in enabled and not keywords
        if skip:
            logger.info(f'skipping {cls.__name__}, not explicitly enabled')
        return skip or super().skip(namespace)


class NetworkCheck(Check):
    """Check that is only run when network support is enabled."""

    @classmethod
    def skip(cls, namespace):
        skip = not namespace.net
        if skip:
            logger.info(f'skipping {cls.__name__}, network checks not enabled')
        elif 'requests_session' not in namespace:
            try:
                from ..net import Session
                # inject requests session into namespace for network checks to use
                namespace.requests_session = Session(timeout=namespace.timeout)
            except ImportError as e:
                if e.name != 'requests':
                    raise
                # skip network checks when requests module isn't installed
                skip = True
                logger.info(f'skipping {cls.__name__}, failed importing requests')
        return skip or super().skip(namespace)
