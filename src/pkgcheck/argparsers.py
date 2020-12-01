"""Various argparse-related support."""

import argparse
from itertools import chain

from snakeoil.cli import arghparse
from snakeoil.mappings import ImmutableDict
from snakeoil.strings import pluralism

from . import base, objects
from .caches import CachedAddon
from .checks import NetworkCheck


class ConfigArg(argparse._StoreAction):
    """Store config path string or False when explicitly disabled."""

    def __call__(self, parser, namespace, values, option_string=None):
        if values.lower() in ('false', 'no', 'n'):
            values = False
        setattr(namespace, self.dest, values)


class EnableNet(argparse.Action):
    """Enable checks that require network access."""

    def __call__(self, parser, namespace, values, option_string=None):
        namespace.enabled_checks.update(
            v for v in objects.CHECKS.values() if issubclass(v, NetworkCheck))
        setattr(namespace, self.dest, True)


class CacheNegations(arghparse.CommaSeparatedNegations):
    """Split comma-separated enabled and disabled cache types."""

    caches = ImmutableDict({cache.type: True for cache in CachedAddon.caches.values()})

    def __init__(self, *args, **kwargs):
        # delay setting default since it has to be mutable
        default = arghparse.DelayedValue(self._cache_defaults, 100)
        super().__init__(*args, default=default, **kwargs)

    def _cache_defaults(self, namespace, attr):
        setattr(namespace, attr, dict(self.caches))

    def parse_values(self, values):
        all_cache_types = {cache.type for cache in CachedAddon.caches.values()}
        disabled, enabled = [], list(all_cache_types)
        if values is None or values.lower() in ('y', 'yes', 'true'):
            pass
        elif values.lower() in ('n', 'no', 'false'):
            disabled = list(all_cache_types)
        else:
            disabled, enabled = super().parse_values(values)
        disabled = set(disabled)
        enabled = set(enabled) if enabled else all_cache_types
        unknown = (disabled | enabled) - all_cache_types
        if unknown:
            unknowns = ', '.join(map(repr, unknown))
            choices = ', '.join(map(repr, sorted(self.caches)))
            s = pluralism(unknown)
            raise argparse.ArgumentError(
                self, f'unknown cache type{s}: {unknowns} (choose from {choices})')
        enabled = set(enabled).difference(disabled)
        return enabled

    def __call__(self, parser, namespace, values, option_string=None):
        enabled = self.parse_values(values)
        caches = {}
        for cache in CachedAddon.caches.values():
            caches[cache.type] = cache.type in enabled
        setattr(namespace, self.dest, caches)


class ScopeArgs(arghparse.CommaSeparatedNegations):
    """Filter enabled checks by selected scopes."""

    def __call__(self, parser, namespace, values, option_string=None):
        disabled, enabled = self.parse_values(values)

        # validate selected scopes
        unknown_scopes = set(disabled + enabled) - set(base.scopes)
        if unknown_scopes:
            unknown = ', '.join(map(repr, unknown_scopes))
            available = ', '.join(base.scopes)
            s = pluralism(unknown_scopes)
            raise argparse.ArgumentError(
                self, f'unknown scope{s}: {unknown} (available scopes: {available})')

        disabled = {base.scopes[x] for x in disabled}
        enabled = {base.scopes[x] for x in enabled}

        if enabled:
            namespace.enabled_checks = {
                c for c in objects.CHECKS.values() if c.scope in enabled}
        if disabled:
            namespace.enabled_checks.difference_update(
                c for c in objects.CHECKS.values() if c.scope in disabled)

        setattr(namespace, self.dest, frozenset(enabled))


class CheckArgs(arghparse.CommaSeparatedNegations):
    """Determine checks to run on selection."""

    def split_enabled(self, enabled):
        """Split explicitly enabled checks into singular and additive groups."""
        singular, additive = [], []
        for token in enabled:
            if token[0] == '+':
                if not token[1:]:
                    raise argparse.ArgumentTypeError("'+' without a token")
                additive.append(token[1:])
            else:
                singular.append(token)
        return singular, additive

    def __call__(self, parser, namespace, values, option_string=None):
        disabled, enabled = self.parse_values(values)
        enabled, additive = self.split_enabled(enabled)

        network = (c for c, v in objects.CHECKS.items() if issubclass(v, NetworkCheck))
        alias_map = {'all': objects.CHECKS, 'net': network}
        replace_aliases = lambda x: alias_map.get(x, [x])

        # expand check aliases to check lists
        disabled = list(chain.from_iterable(map(replace_aliases, disabled)))
        enabled = list(chain.from_iterable(map(replace_aliases, enabled)))
        additive = list(chain.from_iterable(map(replace_aliases, additive)))

        # validate selected checks
        unknown_checks = set(disabled + enabled + additive) - set(objects.CHECKS)
        if unknown_checks:
            unknown = ', '.join(map(repr, unknown_checks))
            s = pluralism(unknown_checks)
            raise argparse.ArgumentError(self, f'unknown check{s}: {unknown}')

        if enabled:
            # replace the default check set
            namespace.enabled_checks = {objects.CHECKS[c] for c in enabled}
        if additive:
            # add to the default check set
            namespace.enabled_checks.update(objects.CHECKS[c] for c in additive)
        if disabled:
            # remove from the default check set
            namespace.enabled_checks.difference_update(
                objects.CHECKS[c] for c in disabled)

        setattr(namespace, self.dest, frozenset(enabled + additive))


class KeywordArgs(arghparse.CommaSeparatedNegations):
    """Filter enabled keywords by selected keywords."""

    def __call__(self, parser, namespace, values, option_string=None):
        disabled, enabled = self.parse_values(values)

        alias_map = {
            'error': objects.KEYWORDS.error,
            'warning': objects.KEYWORDS.warning,
            'info': objects.KEYWORDS.info,
        }
        replace_aliases = lambda x: alias_map.get(x, [x])

        # expand keyword aliases to keyword lists
        disabled = list(chain.from_iterable(map(replace_aliases, disabled)))
        enabled = list(chain.from_iterable(map(replace_aliases, enabled)))

        # validate selected keywords
        unknown_keywords = set(disabled + enabled) - set(objects.KEYWORDS)
        if unknown_keywords:
            unknown = ', '.join(map(repr, unknown_keywords))
            s = pluralism(unknown_keywords)
            raise argparse.ArgumentError(self, f'unknown keyword{s}: {unknown}')

        disabled_keywords = {objects.KEYWORDS[k] for k in disabled}
        enabled_keywords = {objects.KEYWORDS[k] for k in enabled}
        # allow keyword args to be filtered by output name in addition to class name
        disabled_keywords.update(
            k for k in objects.KEYWORDS.values() if k.name in disabled)
        enabled_keywords.update(
            k for k in objects.KEYWORDS.values() if k.name in enabled)

        # determine keywords to filter
        if not enabled_keywords:
            # disable checks that have all their keywords disabled
            for check in list(namespace.enabled_checks):
                if check.known_results.issubset(disabled_keywords):
                    namespace.enabled_checks.discard(check)
            enabled_keywords = set().union(
                *(c.known_results for c in namespace.enabled_checks))

        namespace.filtered_keywords = enabled_keywords - disabled_keywords
        # restrict enabled checks if none have been selected
        if not namespace.selected_checks:
            namespace.enabled_checks = set()
            for check in objects.CHECKS.values():
                if namespace.filtered_keywords.intersection(check.known_results):
                    namespace.enabled_checks.add(check)

        setattr(namespace, self.dest, frozenset(enabled))


class ExitArgs(arghparse.CommaSeparatedNegations):
    """Filter enabled keywords by selected keywords."""

    def __call__(self, parser, namespace, values, option_string=None):
        # default to using error results if no keywords are selected
        if values is None:
            values = 'error'

        disabled, enabled = self.parse_values(values)

        # if only disabled arguments are passed, enable error results as exit failures
        if not enabled:
            enabled.append('error')

        alias_map = {
            'error': objects.KEYWORDS.error,
            'warning': objects.KEYWORDS.warning,
            'info': objects.KEYWORDS.info,
        }
        replace_aliases = lambda x: alias_map.get(x, [x])

        # expand keyword aliases to keyword lists
        disabled = list(chain.from_iterable(map(replace_aliases, disabled)))
        enabled = list(chain.from_iterable(map(replace_aliases, enabled)))

        # validate selected keywords
        unknown_keywords = set(disabled + enabled) - set(objects.KEYWORDS)
        if unknown_keywords:
            unknown = ', '.join(map(repr, unknown_keywords))
            s = pluralism(unknown_keywords)
            raise argparse.ArgumentError(self, f'unknown keyword{s}: {unknown}')

        disabled = {objects.KEYWORDS[k] for k in disabled}
        enabled = {objects.KEYWORDS[k] for k in enabled}
        exit_keywords = frozenset(enabled - disabled)

        setattr(namespace, self.dest, exit_keywords)
