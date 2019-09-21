"""Core check classes."""

from .. import base, sources
from ..log import logger


class GentooRepoCheck(base.Check):
    """Check that is only valid when run against the gentoo repo."""

    @classmethod
    def skip(cls, namespace):
        skip = not namespace.gentoo_repo
        if skip:
            logger.info(f'skipping {cls.__name__}, not running against gentoo repo')
        return skip or super().skip(namespace)


class OverlayRepoCheck(base.Check):
    """Check that is only valid when run against an overlay repo."""

    @classmethod
    def skip(cls, namespace):
        skip = not namespace.target_repo.masters
        if skip:
            logger.info(f'skipping {cls.__name__}, not running against overlay repo')
        return skip or super().skip(namespace)


class ExplicitlyEnabledCheck(base.Check):
    """Check that is only valid when explicitly enabled."""

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


class NetworkCheck(base.Check):
    """Check requiring internet access."""

    @classmethod
    def skip(cls, namespace):
        skip = not namespace.net
        if skip:
            logger.info(f'skipping {cls.__name__}, network checks not enabled')
        return skip or super().skip(namespace)
