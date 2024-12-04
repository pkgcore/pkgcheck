"""Various argparse-related support."""

import argparse
from itertools import chain

from snakeoil.cli import arghparse
from snakeoil.mappings import ImmutableDict
from snakeoil.strings import pluralism

from .. import base, objects
from ..addons.caches import CachedAddon
from ..checks import NetworkCheck


class ConfigArg(argparse._StoreAction):
    """Store config path string or False when explicitly disabled."""

    def __call__(self, parser, namespace, values, option_string=None):
        if values.lower() in ("false", "no", "n"):
            values = False
        setattr(namespace, self.dest, values)


def object_to_keywords(namespace, obj):
    """Convert a given object into a generator of its respective keyword names."""
    if obj in objects.KEYWORDS:
        yield obj
    elif obj in objects.CHECKS:
        yield from (x.__name__ for x in objects.CHECKS[obj].known_results)
    elif obj in namespace.config_checksets:
        yield from chain(*ChecksetArgs.checksets_to_keywords(namespace, [obj]))
    else:
        raise ValueError(f"unknown checkset, check, or keyword: {obj!r}")


class FilterArgs(arghparse.CommaSeparatedValues):
    """Apply filters to an entire scan or specific checks/keywords."""

    known_filters = frozenset(["latest"])

    def __call__(self, parser, namespace, values, option_string=None):
        values = self.parse_values(values)
        filter_map = {}
        disabled = False

        for val in values:
            if ":" in val:
                filter_type, target = val.split(":")
                try:
                    keywords = object_to_keywords(namespace, target)
                    filter_map.update({x: filter_type for x in keywords})
                except ValueError as e:
                    raise argparse.ArgumentError(self, str(e))
            elif val.lower() in ("false", "no", "n"):
                # disable all filters
                disabled = True
                break
            else:
                # globally enabling filter
                filter_map.update((x, val) for x in objects.KEYWORDS)
                break

        # validate selected filters
        if unknown := set(filter_map.values()) - self.known_filters:
            s = pluralism(unknown)
            unknown = ", ".join(map(repr, unknown))
            available = ", ".join(sorted(self.known_filters))
            raise argparse.ArgumentError(
                self, f"unknown filter{s}: {unknown} (available: {available})"
            )

        filters = {}
        if not disabled:
            # pull default filters
            filters.update(objects.KEYWORDS.filter)
            # ignore invalid keywords -- only keywords version scope and higher are affected
            filters.update(
                {
                    objects.KEYWORDS[k]: v
                    for k, v in filter_map.items()
                    if objects.KEYWORDS[k].scope >= base.version_scope
                }
            )

        setattr(namespace, self.dest, ImmutableDict(filters))


class EnableNet(argparse.Action):
    """Enable checks that require network access."""

    def __call__(self, parser, namespace, values, option_string=None):
        namespace.enabled_checks.update(objects.CHECKS.select(NetworkCheck).values())
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
        if values is None or values.lower() in ("y", "yes", "true"):
            pass
        elif values.lower() in ("n", "no", "false"):
            disabled = list(all_cache_types)
        else:
            disabled, enabled = super().parse_values(values)
        disabled = set(disabled)
        enabled = set(enabled) if enabled else all_cache_types
        if unknown := (disabled | enabled) - all_cache_types:
            unknowns = ", ".join(map(repr, unknown))
            choices = ", ".join(map(repr, sorted(self.caches)))
            s = pluralism(unknown)
            raise argparse.ArgumentError(
                self, f"unknown cache type{s}: {unknowns} (choose from {choices})"
            )
        enabled = set(enabled).difference(disabled)
        return enabled

    def __call__(self, parser, namespace, values, option_string=None):
        enabled = self.parse_values(values)
        caches = {}
        for cache in CachedAddon.caches.values():
            caches[cache.type] = cache.type in enabled
        setattr(namespace, self.dest, caches)


class ChecksetArgs(arghparse.CommaSeparatedNegations):
    """Filter enabled checks/keywords by selected checksets."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.aliases = {
            "all": list(objects.CHECKS.values()),
            "net": list(objects.CHECKS.select(NetworkCheck).values()),
        }

    def expand_aliases(self, args):
        """Expand internal checkset aliases into keyword generators."""
        checksets, keywords = [], []
        for arg in args:
            try:
                for check in self.aliases[arg]:
                    keywords.extend(x.__name__ for x in check.known_results)
            except KeyError:
                checksets.append(arg)
        return checksets, keywords

    @staticmethod
    def checksets_to_keywords(namespace, args):
        """Expand checksets into lists of disabled and enabled keywords."""
        disabled, enabled = [], []
        for arg in args:
            for x in namespace.config_checksets[arg]:
                # determine if checkset item is disabled or enabled
                if x[0] == "-":
                    x = x[1:]
                    keywords = disabled
                else:
                    keywords = enabled
                # determine if checkset item is check or keyword
                if x in objects.CHECKS:
                    keywords.extend(x.__name__ for x in objects.CHECKS[x].known_results)
                elif x in objects.KEYWORDS:
                    keywords.append(x)
                else:
                    raise ValueError(f"{arg!r} checkset, unknown check or keyword: {x!r}")
        return disabled, enabled

    def __call__(self, parser, namespace, values, option_string=None):
        disabled, enabled = self.parse_values(values)
        checksets = namespace.config_checksets

        # validate selected checksets
        if unknown := set(disabled + enabled) - set(self.aliases) - set(checksets):
            unknown_str = ", ".join(map(repr, unknown))
            available = ", ".join(sorted(chain(checksets, self.aliases)))
            s = pluralism(unknown)
            raise argparse.ArgumentError(
                self, f"unknown checkset{s}: {unknown_str} (available: {available})"
            )

        # expand aliases into keywords
        disabled, disabled_aliases = self.expand_aliases(disabled)
        enabled, enabled_aliases = self.expand_aliases(enabled)

        # expand checksets into keywords
        try:
            disabled = self.checksets_to_keywords(namespace, disabled)
            enabled = self.checksets_to_keywords(namespace, enabled)
        except ValueError as e:
            raise argparse.ArgumentError(self, str(e))

        # Convert double negatives into positives, e.g. disabling a checkset
        # containing a disabled keyword enables the keyword.
        disabled_keywords = set(disabled_aliases + disabled[1] + enabled[0])
        enabled_keywords = set(enabled_aliases + disabled[0] + enabled[1]) - disabled_keywords

        # parse check/keyword args related to checksets
        args = []
        if enabled_keywords:
            keywords_set = {objects.KEYWORDS[x] for x in enabled_keywords}
            checks = ",".join(
                k for k, v in objects.CHECKS.items() if v.known_results.intersection(keywords_set)
            )
            args.append(f"--checks={checks}")
        keywords = ",".join(enabled_keywords | {f"-{x}" for x in disabled_keywords})
        args.append(f"--keywords={keywords}")
        # Python 3.12.8 introduced obligatory intermixed arg.  The same
        # commit adds _parse_known_args2 function, so use that to determine
        # if we need to pass that.
        if hasattr(parser, "_parse_known_args2"):
            parser._parse_known_args(args, namespace, intermixed=False)
        else:
            parser._parse_known_args(args, namespace)


class ScopeArgs(arghparse.CommaSeparatedNegations):
    """Filter enabled checks by selected scopes."""

    def __call__(self, parser, namespace, values, option_string=None):
        disabled, enabled = self.parse_values(values)

        # validate selected scopes
        if unknown_scopes := set(disabled + enabled) - set(base.scopes):
            unknown = ", ".join(map(repr, unknown_scopes))
            available = ", ".join(base.scopes)
            s = pluralism(unknown_scopes)
            raise argparse.ArgumentError(
                self, f"unknown scope{s}: {unknown} (available: {available})"
            )

        disabled = set(chain.from_iterable(base.scopes[x] for x in disabled))
        enabled = set(chain.from_iterable(base.scopes[x] for x in enabled))

        if enabled:
            namespace.enabled_checks = {c for c in objects.CHECKS.values() if c.scope in enabled}
        if disabled:
            namespace.enabled_checks.difference_update(
                c for c in objects.CHECKS.values() if c.scope in disabled
            )

        setattr(namespace, self.dest, frozenset(enabled))


class CheckArgs(arghparse.CommaSeparatedElements):
    """Determine checks to run on selection."""

    def __call__(self, parser, namespace, values, option_string=None):
        subtractive, neutral, additive = self.parse_values(values)

        # validate selected checks
        if unknown_checks := set(subtractive + neutral + additive) - set(objects.CHECKS):
            unknown = ", ".join(map(repr, unknown_checks))
            s = pluralism(unknown_checks)
            raise argparse.ArgumentError(self, f"unknown check{s}: {unknown}")

        if neutral:
            # replace the default check set
            namespace.enabled_checks = {objects.CHECKS[c] for c in neutral}
        if additive:
            # add to the default check set
            namespace.enabled_checks.update(objects.CHECKS[c] for c in additive)
        if subtractive:
            # remove from the default check set
            namespace.enabled_checks.difference_update(objects.CHECKS[c] for c in subtractive)

        setattr(namespace, self.dest, frozenset(neutral + additive))


class KeywordArgs(arghparse.CommaSeparatedNegations):
    """Filter enabled keywords by selected keywords."""

    def __call__(self, parser, namespace, values, option_string=None):
        disabled, enabled = self.parse_values(values)
        replace_aliases = lambda x: objects.KEYWORDS.aliases.get(x, [x])

        # expand keyword aliases to keyword lists
        disabled = list(chain.from_iterable(map(replace_aliases, disabled)))
        enabled = list(chain.from_iterable(map(replace_aliases, enabled)))

        # validate selected keywords
        if unknown_keywords := set(disabled + enabled) - set(objects.KEYWORDS):
            unknown = ", ".join(map(repr, unknown_keywords))
            s = pluralism(unknown_keywords)
            raise argparse.ArgumentError(self, f"unknown keyword{s}: {unknown}")

        # create keyword instance sets
        disabled_keywords = {objects.KEYWORDS[k] for k in disabled}
        enabled_keywords = {objects.KEYWORDS[k] for k in enabled}

        # determine keywords to filter
        if not enabled_keywords:
            # disable checks that have all their keywords disabled
            for check in list(namespace.enabled_checks):
                if check.known_results.issubset(disabled_keywords):
                    namespace.enabled_checks.discard(check)
            enabled_keywords = set().union(*(c.known_results for c in namespace.enabled_checks))

        namespace.filtered_keywords = enabled_keywords - disabled_keywords
        if namespace.verbosity < 0:  # quiet mode, include only errors
            namespace.filtered_keywords = {
                x for x in namespace.filtered_keywords if x.level == "error"
            }
        # restrict enabled checks if none have been selected
        if not namespace.selected_checks:
            namespace.enabled_checks = set()
            for check in objects.CHECKS.values():
                if namespace.filtered_keywords.intersection(check.known_results):
                    namespace.enabled_checks.add(check)

        # check if experimental profiles are required for explicitly selected keywords
        for r in namespace.filtered_keywords:
            if r.name in enabled and r._profile == "exp":
                namespace.exp_profiles_required = True
                break

        setattr(namespace, self.dest, frozenset(enabled))


class ExitArgs(arghparse.CommaSeparatedElements):
    """Filter enabled keywords by selected keywords."""

    def args_to_keywords(self, namespace, args):
        """Expand arguments to keyword names."""
        keywords = []
        for val in args:
            try:
                keywords.extend(objects.KEYWORDS.aliases[val])
            except KeyError:
                try:
                    keywords.extend(object_to_keywords(namespace, val))
                except ValueError as e:
                    raise argparse.ArgumentError(self, str(e))
        return keywords

    def __call__(self, parser, namespace, values, option_string=None):
        # default to using error results if no keywords are selected
        if values is None:
            values = "error"

        subtractive, neutral, additive = self.parse_values(values)

        # default to using error results if no neutral keywords are selected
        if not neutral:
            neutral.append("error")

        # expand args to keyword objects
        keywords = {objects.KEYWORDS[x] for x in self.args_to_keywords(namespace, neutral)}
        keywords.update(objects.KEYWORDS[x] for x in self.args_to_keywords(namespace, additive))
        keywords.difference_update(
            objects.KEYWORDS[x] for x in self.args_to_keywords(namespace, subtractive)
        )

        setattr(namespace, self.dest, frozenset(keywords))
