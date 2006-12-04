# Copyright: 2006 Marien Zwart <marienz@gentoo.org>
# License: GPL2


"""Addon functionality shared by multiple checkers."""


import optparse
from itertools import chain, ifilter

from pkgcore_checks import base, util

from pkgcore.util import demandload, currying, containers, mappings
demandload.demandload(
    globals(),
    'os '
    'pkgcore.util:osutils '
    'pkgcore.restrictions:packages,values '
    'pkgcore.ebuild:domain,profiles '
    )


class ArchesAddon(base.Addon):

    default_arches = tuple(sorted([
                    "x86", "x86-fbsd", "amd64", "ppc", "ppc-macos", "ppc64",
                    "sparc", "mips", "arm", "hppa", "m68k", "ia64", "s390",
                    "sh", "alpha"]))

    @staticmethod
    def _record_arches(option, opt_str, value, parser):
        setattr(parser.values, option.dest, tuple(value.split(",")))

    @classmethod
    def mangle_option_parser(cls, parser):
        parser.add_option(
            '-a', '--arches', action='callback', callback=cls._record_arches,
            type='string', default=cls.default_arches,
            help="comma seperated list of what arches to run, defaults to %s" %
            ",".join(cls.default_arches))


class QueryCacheAddon(base.Addon):

    feed_type = base.package_feed
    scope = base.version_scope
    priority = 1

    @staticmethod
    def mangle_option_parser(parser):
        group = parser.add_option_group('Query caching')
        group.add_option(
            "--reset-caching-per-category", action='store_const',
            dest='query_caching_freq', const=base.category_feed,
            help="clear query caching after every category (defaults to every "
            "package)")
        group.add_option(
            "--reset-caching-per-package", action='store_const',
            dest='query_caching_freq', const=base.package_feed,
            help="clear query caching after ever package (the default)")
        # XXX does this const work?
        group.add_option(
            "--reset-caching-per-version", action='store_const',
            dest='query_caching_freq', const='version_feed',
            help="clear query caching after ever version (defaults to every "
            "package)")
        parser.set_default('query_caching_freq', base.package_feed)

    def __init__(self, options):
        base.Addon.__init__(self, options)
        self.query_cache = {}
        self.enabling_threshold = self.options.query_caching_freq

    def feed(self, pkgs, reporter):
        for pkgset in pkgs:
            yield pkgset
            self.query_cache.clear()


class profile_data(object):

    def __init__(self, profile_name, key, virtuals, provides, vfilter,
        masked_use, forced_use, lookup_cache, insoluable):
        self.key = key
        self.name = profile_name
        self.virtuals = virtuals
        self.provides_repo = provides
        self.masked_use = masked_use
        self.forced_use = forced_use
        self.cache = lookup_cache
        self.insoluable = insoluable
        self.visible = vfilter.match

    def identify_use(self, pkg, known_flags):
        # note we're trying to be *really* careful about not creating
        # pointless intermediate sets unless required
        # kindly don't change that in any modifications, it adds up.
        enabled = known_flags.intersection(
            domain.generic_collapse_data(self.forced_use, pkg))
        immutable = frozenset(chain(enabled,
            ifilter(known_flags.__contains__,
            domain.generic_collapse_data(self.masked_use, pkg))
            ))
        return immutable, enabled


class ProfileAddon(base.Addon):

    @staticmethod
    def check_values(values):
        if values.profiles_enabled is None:
            values.profiles_enabled = []
        if values.profiles_disabled is None:
            values.profiles_disabled = []
        profile_loc = getattr(values, "profile_dir", None)

        if profile_loc is not None:
            if not os.path.isdir(profile_loc):
                raise optparse.OptionValueError(
                    "profile-base location %r doesn't exist/isn't a dir" % (
                        profile_loc,))
        else:
            # TODO improve this to handle multiple profiles dirs.
            repo_base = getattr(values.src_repo, 'base', None)
            if repo_base is None:
                raise optparse.OptionValueError(
                    'Need a target repo or --overlayed-repo that is a single '
                    'UnconfiguredTree for profile checks')
            profile_loc = os.path.join(repo_base, "profiles")
            if not os.path.isdir(profile_loc):
                raise optparse.OptionValueError(
                    "repo %r lacks a profiles directory" % (values.src_repo,))

        profile_loc = osutils.abspath(profile_loc)
        values.profile_func = currying.pre_curry(util.get_profile_from_path,
                                                 profile_loc)
        values.profile_base_dir = profile_loc

    @staticmethod
    def mangle_option_parser(parser):
        group = parser.add_option_group('Profiles')
        group.add_option(
            "--profile-base", action='store', type='string',
            dest='profile_dir', default=None,
            help="filepath to base profiles directory")
        group.add_option(
            "--profile-disable-dev", action='store_true',
            default=False, dest='profile_ignore_dev',
            help="disable scanning of dev profiles")
        group.add_option(
            "--profile-disable-deprecated", action='store_true',
            default=False, dest='profile_ignore_deprecated',
            help="disable scanning of deprecated profiles")
        group.add_option(
            "--profile-disable-profiles-desc", action='store_false',
            default=True, dest='profiles_desc_enabled',
            help="disable loading profiles to scan from profiles.desc, you "
            "will want to enable profiles manually via --profile-enable")
        group.add_option(
            '--profile-enable', action='append', type='string',
            dest='profiles_enabled', help="specify a profile to scan")
        group.add_option(
            '--profile-disable', action='append', type='string',
            dest='profiles_disabled', help="specify a profile to ignore")

    def __init__(self, options, *args):
        base.Addon.__init__(self, options)

        def norm_name(name):
            return '/'.join(y for y in name.split('/') if y)

        disabled = set(norm_name(x) for x in options.profiles_disabled)
        enabled = set(x for x in 
            (norm_name(y) for y in options.profiles_enabled)
            if x not in disabled)

        arch_profiles = {}
        if options.profiles_desc_enabled:
            d = \
                util.get_profiles_desc(options.profile_base_dir,
                    ignore_dev=options.profile_ignore_dev)
            
            for k, v in d.iteritems():
                l = [x for x in map(norm_name, v)
                    if not x in disabled]
                
                # wipe any enableds that are here already so we don't 
                # get a profile twice
                enabled.difference_update(l)
                if v:
                    arch_profiles[k] = l

        for x in enabled:
            p = options.profile_func(x)
            arch = p.arch
            if arch is None:
                raise profiles.ProfileError(p.path, 'make.defaults',
                    "profile %s lacks arch settings, unable to use it" % x)
            arch_profiles.setdefault(p.arch, []).append((x, p))
            
        for x in options.profiles_enabled:
            options.profile_func(x)

        self.official_arches = util.get_repo_known_arches(
            options.profile_base_dir)

        self.desired_arches = getattr(self.options, 'arches', None)
        if self.desired_arches is None:
            # copy it to be safe
            self.desired_arches = set(self.official_arches)

        self.global_insoluable = set()
        profile_filters = {}
        self.keywords_filter = {}
#        profile_evaluate_dict = {}
        ignore_deprecated = self.options.profile_ignore_deprecated
        
        for k in self.desired_arches:
            if k.lstrip("~") not in self.desired_arches:
                continue
            stable_key = k.lstrip("~")
            unstable_key = "~"+ stable_key
            stable_r = packages.PackageRestriction("keywords", 
                values.ContainmentMatch(stable_key))
            unstable_r = packages.PackageRestriction("keywords", 
                values.ContainmentMatch(stable_key, unstable_key))
            
            default_masked_use = [(packages.AlwaysTrue, (x,)) for x in
                self.official_arches if x != stable_key]
            
            profile_filters.update({stable_key:[], unstable_key:[]})
            for profile_name in arch_profiles.get(k, []):
                if not isinstance(profile_name, basestring):
                    profile_name, profile = profile_name
                else:
                    profile = options.profile_func(profile_name)
                if ignore_deprecated and profile.deprecated:
                    continue

                mask = domain.generate_masking_restrict(profile.masks)
                virtuals = profile.make_virtuals_repo(options.search_repo)

                immutable_flags = domain.make_data_dict(
                    default_masked_use,
                    profile.masked_use.iteritems())
                enabled_flags = domain.make_data_dict(
                    [(packages.AlwaysTrue, (stable_key,))],
                    profile.forced_use.iteritems())
                
                # used to interlink stable/unstable lookups so that if 
                # unstable says it's not visible, stable doesn't try
                # if stable says something is visible, unstable doesn't try.
                stable_cache = set()
                unstable_insoluable = containers.ProtectedSet(
                    self.global_insoluable)

                # few notes.  for filter, ensure keywords is last, on the
                # offchance a non-metadata based restrict foregos having to
                # access the metadata.
                # note that the cache/insoluable are inversly paired;
                # stable cache is usable for unstable, but not vice versa.
                # unstable insoluable is usable for stable, but not vice versa

                profile_filters[stable_key].append(profile_data(
                    profile_name, stable_key,
                    virtuals, profile.provides_repo,
                    packages.AndRestriction(mask, stable_r),
                    immutable_flags, enabled_flags, stable_cache,
                    containers.ProtectedSet(unstable_insoluable)))

                profile_filters[unstable_key].append(profile_data(
                    profile_name, unstable_key,
                    virtuals, profile.provides_repo,
                    packages.AndRestriction(mask, unstable_r),
                    immutable_flags, enabled_flags,
                    containers.ProtectedSet(stable_cache),
                    unstable_insoluable))

#                for k in (stable_key, unstable_key):
#                    profile_evaluate_dict.setdefault(k, {}).setdefault(
#                        (non_tristate, use_flags), []).append(
#                            (package_use_mask, package_use_force, profile_name))

            self.keywords_filter[stable_key] = stable_r
            self.keywords_filter[unstable_key] = packages.PackageRestriction(
                "keywords", 
                values.ContainmentMatch(unstable_key))

        self.arch_profiles = arch_profiles
        self.keywords_filter = mappings.OrderedDict(
            (k, self.keywords_filter[k])
            for k in sorted(self.keywords_filter))
        self.profile_filters = profile_filters
#        self.profile_evaluate_dict = profile_evaluate_dict

    def identify_profiles(self, pkg):
        l = []
        for key in set(pkg.keywords):
            for profile in self.profile_filters.get(key, ()):
                if not profile.visible(pkg):
                    continue
                l.append(profile)
        return l


class EvaluateDepSetAddon(base.Addon):

    # XXX QueryCache just for the query_caching_freq option, separate?
    required_addons = (ProfileAddon, QueryCacheAddon)

    feed_type = base.package_feed
    scope = base.version_scope
    priority = 1

    def __init__(self, options, profiles, query_cache, *args):
        base.Addon.__init__(self, options)
        self.pkg_evaluate_depsets_cache = {}
        self.pkg_profiles_cache = {}
        self.profiles = profiles
        self.enabling_threshold = self.options.query_caching_freq

    def feed(self, pkgs, reporter):
        for pkgset in pkgs:
            yield pkgset
            self.pkg_evaluate_depsets_cache.clear()
            self.pkg_profiles_cache.clear()

    def collapse_evaluate_depset(self, pkg, attr, depset):
        depset_profiles = self.pkg_evaluate_depsets_cache.get((pkg, attr))
        if depset_profiles is None:
            depset_profiles = self.identify_common_depsets(pkg, depset)
            self.pkg_evaluate_depsets_cache[(pkg, attr)] = depset_profiles
        return depset_profiles

    def identify_common_depsets(self, pkg, depset):
        pkey = pkg.key
        profiles = self.pkg_profiles_cache.get(pkg, None)
        if profiles is None:
            profiles = self.profiles.identify_profiles(pkg)
            self.pkg_profiles_cache[pkg] = profiles
        diuse = depset.known_conditionals
        collapsed = {}
        for profile in profiles:
            immutables, enabled = profile.identify_use(pkg, diuse)
            collapsed.setdefault((immutables, enabled), []).append(profile)

        return [(depset.evaluate_depset(k[1], tristate_filter=k[0]), v)
            for k,v in collapsed.iteritems()]



class LicenseAddon(base.Addon):

    @staticmethod
    def mangle_option_parser(parser):
        parser.add_option(
            "--license-dir", action='store', type='string',
            help="filepath to license directory")

    @staticmethod
    def check_values(values):
        values.license_dirs = []
        if values.license_dir is None:
            for repo_base in values.repo_bases:
                candidate = os.path.join(repo_base, 'licenses')
                if os.path.isdir(candidate):
                    values.license_dirs.append(candidate)
            if not values.license_dirs:
                raise optparse.OptionValueError(
                    'No license dir detected, pick a target or overlayed repo '
                    'with a license dir or specify one with --license-dir.')
        else:
            if not os.path.isdir(values.license_dir):
                raise optparse.OptionValueError(
                    "--license-dir %r isn't a directory" % values.license_dir)
            values.license_dirs.append(osutils.abspath(values.license_dir))
