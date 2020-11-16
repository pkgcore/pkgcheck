"""Various argparse-related support."""

import argparse
from itertools import chain

from snakeoil.cli import arghparse
from snakeoil.strings import pluralism

from . import base, objects, results
from .caches import CachedAddon
from .checks import NetworkCheck


class ConfigArg(argparse._StoreAction):
    """Store config path string or False when explicitly disabled."""

    def __call__(self, parser, namespace, values, option_string=None):
        if values.lower() in ('false', 'no', 'n'):
            values = False
        setattr(namespace, self.dest, values)


class CacheNegations(arghparse.CommaSeparatedNegations):
    """Split comma-separated enabled and disabled cache types."""

    default = {cache.type: True for cache in CachedAddon.caches.values()}

    def parse_values(self, values):
        all_cache_types = {cache.type for cache in CachedAddon.caches.values()}
        disabled, enabled = [], list(all_cache_types)
        if values is None or values in ('y', 'yes', 'true'):
            pass
        elif values in ('n', 'no', 'false'):
            disabled = list(all_cache_types)
        else:
            disabled, enabled = super().parse_values(values)
        disabled = set(disabled)
        enabled = set(enabled) if enabled else all_cache_types
        unknown = (disabled | enabled) - all_cache_types
        if unknown:
            unknowns = ', '.join(map(repr, unknown))
            choices = ', '.join(map(repr, sorted(self.default)))
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
    """Filter enabled keywords by selected scopes."""

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

        setattr(namespace, self.dest, (disabled, enabled))


class KeywordArgs(arghparse.CommaSeparatedNegations):
    """Filter enabled keywords by selected keywords."""

    def __call__(self, parser, namespace, values, option_string=None):
        disabled, enabled = self.parse_values(values)

        error = (k for k, v in objects.KEYWORDS.items() if issubclass(v, results.Error))
        warning = (k for k, v in objects.KEYWORDS.items() if issubclass(v, results.Warning))
        info = (k for k, v in objects.KEYWORDS.items() if issubclass(v, results.Info))
        alias_map = {'error': error, 'warning': warning, 'info': info}
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

        setattr(namespace, self.dest, (disabled, enabled))


class CheckArgs(arghparse.CommaSeparatedNegations):
    """Determine checks to run on selection."""

    def __call__(self, parser, namespace, values, option_string=None):
        disabled, enabled = self.parse_values(values)

        network = (c for c, v in objects.CHECKS.items() if issubclass(v, NetworkCheck))
        alias_map = {'all': objects.CHECKS, 'net': network}
        replace_aliases = lambda x: alias_map.get(x, [x])

        # expand check aliases to check lists
        disabled = list(chain.from_iterable(map(replace_aliases, disabled)))
        enabled = list(chain.from_iterable(map(replace_aliases, enabled)))

        # validate selected checks
        unknown_checks = set(disabled + enabled) - set(objects.CHECKS)
        if unknown_checks:
            unknown = ', '.join(map(repr, unknown_checks))
            s = pluralism(unknown_checks)
            raise argparse.ArgumentError(self, f'unknown check{s}: {unknown}')

        setattr(namespace, self.dest, (disabled, enabled))


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

        error = (k for k, v in objects.KEYWORDS.items() if issubclass(v, results.Error))
        warning = (k for k, v in objects.KEYWORDS.items() if issubclass(v, results.Warning))
        info = (k for k, v in objects.KEYWORDS.items() if issubclass(v, results.Info))
        alias_map = {'error': error, 'warning': warning, 'info': info}
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
