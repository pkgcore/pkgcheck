from operator import attrgetter

from snakeoil.mappings import defaultdictkey
from snakeoil.strings import pluralism

from .. import addons, results, sources
from . import Check


class RedundantVersion(results.VersionResult, results.Info):
    """Redundant version(s) of a package in a specific slot."""

    def __init__(self, slot, later_versions, **kwargs):
        super().__init__(**kwargs)
        self.slot = slot
        self.later_versions = tuple(later_versions)

    @property
    def desc(self):
        s = pluralism(self.later_versions)
        versions = ', '.join(self.later_versions)
        return f'slot({self.slot}) keywords are overshadowed by version{s}: {versions}'


class RedundantVersionCheck(Check):
    """Scan for overshadowed package versions.

    Scan for versions that are likely shadowed by later versions from a
    keywords standpoint (ignoring live packages that erroneously have
    keywords).

    Example: pkga-1 is keyworded amd64, pkga-2 is amd64.
    pkga-1 can potentially be removed.
    """

    _source = sources.PackageRepoSource
    required_addons = (addons.profiles.ProfileAddon,)
    known_results = frozenset([RedundantVersion])

    @staticmethod
    def mangle_argparser(parser):
        parser.plugin.add_argument(
            '--stable-only', action='store_true',
            help='consider redundant versions only within stable',
            docs="""
                If enabled, for each slot, only consider redundant versions
                with stable keywords. This is useful for cases of cleanup after
                successful stabilization.
            """)

    def __init__(self, *args, profile_addon):
        super().__init__(*args)
        self.keywords_profiles = {
            keyword: sorted(profiles, key=attrgetter('name'))
            for keyword, profiles in profile_addon.items()}

    def filter_later_profiles_masks(self, visible_cache, pkg, later_versions):
        # check both stable/unstable profiles for stable KEYWORDS and only
        # unstable profiles for unstable KEYWORDS
        keywords = []
        for keyword in pkg.sorted_keywords:
            if keyword[0] != '~':
                keywords.append('~' + keyword)
            keywords.append(keyword)

        # if a profile exists, where the package is visible, but the later aren't
        # then it isn't redundant
        visible_profiles = tuple(profile
            for keyword in keywords
            for profile in self.keywords_profiles.get(keyword, ())
            if visible_cache[(profile, pkg)])
        return tuple(
            later for later in later_versions
            if all(visible_cache[(profile, later)] for profile in visible_profiles))

    def feed(self, pkgset):
        if len(pkgset) == 1:
            return

        # algo is roughly thus; spot stable versions, hunt for subset
        # keyworded pkgs that are less then the max version;
        # repeats this for every overshadowing detected
        # finally, does version comparison down slot lines
        stack = []
        bad = []
        for pkg in reversed(pkgset):
            # reduce false positives for idiot keywords/ebuilds
            if pkg.live:
                continue
            curr_set = {x for x in pkg.keywords if not x.startswith("-")}
            if not curr_set:
                continue

            matches = [ver for ver, keys in stack if ver.slot == pkg.slot and
                       not curr_set.difference(keys)]

            # we've done our checks; now we inject unstable for any stable
            # via this, earlier versions that are unstable only get flagged
            # as "not needed" since their unstable flag is a subset of the
            # stable.

            # also, yes, have to use list comp here- we're adding as we go
            curr_set.update([f'~{x}' for x in curr_set if not x.startswith('~')])

            stack.append((pkg, curr_set))
            if matches:
                bad.append((pkg, matches))

        visible_cache = defaultdictkey(lambda profile_pkg: profile_pkg[0].visible(profile_pkg[1]))
        for pkg, matches in reversed(bad):
            if self.options.stable_only and all(key.startswith('~') for x in matches for key in x.keywords):
                continue
            if matches := self.filter_later_profiles_masks(visible_cache, pkg, matches):
                later_versions = (x.fullver for x in sorted(matches))
                yield RedundantVersion(pkg.slot, later_versions, pkg=pkg)
