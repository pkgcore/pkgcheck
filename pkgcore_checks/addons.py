# Copyright: 2006 Marien Zwart <marienz@gentoo.org>
# License: GPL2


"""Addon functionality shared by multiple checkers."""


import optparse
from itertools import chain

from pkgcore_checks import base, util

from pkgcore.util import demandload, currying, containers, mappings
demandload.demandload(
    globals(),
    'os '
    'pkgcore.util:osutils '
    'pkgcore.restrictions:packages,values '
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


class ProfileAddon(base.Addon):

    def __init__(self, options, *args):
        base.Addon.__init__(self, options)

        def norm_name(x):
            return '/'.join(y for y in x.split('/') if y)

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
                raise pkgcore.config.profiles.ProfileException(
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
        profile_evaluate_dict = {}
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
            
            profile_filters.update({stable_key:{}, unstable_key:{}})
            for profile_name in arch_profiles.get(k, []):
                if not isinstance(profile_name, basestring):
                    profile_name, profile = profile_name
                else:
                    profile = options.profile_func(profile_name)
                if ignore_deprecated and profile.deprecated:
                    continue
                mask = util.get_profile_mask(profile)
                virtuals = profile.virtuals(options.search_repo)
                # force all use masks to negated, and all other arches but this
                non_tristate = frozenset(list(self.official_arches) +
                    list(profile.use_mask) + list(profile.use_force))
                use_flags = frozenset([stable_key] + list(profile.use_force))
                
                package_use_force = profile.package_use_force
                package_use_mask  = profile.package_use_mask
                                
                # used to interlink stable/unstable lookups so that if 
                # unstable says it's not visible, stable doesn't try
                # if stable says something is visible, unstable doesn't try.
                stable_cache = set()
                unstable_insoluable = containers.ProtectedSet(
                    self.global_insoluable)

                # ensure keywords is last, else it triggers a metadata pull
                # filter is thus- not masked, and keywords match

                # virtual repo, flags, visibility filter, known_good, known_bad
                profile_filters[stable_key][profile_name] = [
                    virtuals, package_use_mask, package_use_force,
                    use_flags, non_tristate,
                    packages.AndRestriction(mask, stable_r),
                    stable_cache,
                    containers.ProtectedSet(unstable_insoluable),
                    profile.package_provided_repo]
                profile_filters[unstable_key][profile_name] = [
                    virtuals, package_use_mask, package_use_force,
                    use_flags, non_tristate,
                    packages.AndRestriction(mask, unstable_r), 
                    containers.ProtectedSet(stable_cache), unstable_insoluable,
                    profile.package_provided_repo]
                
                for k in (stable_key, unstable_key):
                    profile_evaluate_dict.setdefault(k, {}).setdefault(
                        (non_tristate, use_flags), []).append(
                            (package_use_mask, package_use_force, profile_name))

            self.keywords_filter[stable_key] = stable_r
            self.keywords_filter[unstable_key] = packages.PackageRestriction(
                "keywords", 
                values.ContainmentMatch(unstable_key))

        self.arch_profiles = arch_profiles
        self.keywords_filter = mappings.OrderedDict(
            (k, self.keywords_filter[k])
            for k in sorted(self.keywords_filter))
        self.profile_filters = profile_filters
        self.profile_evaluate_dict = profile_evaluate_dict

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
            if values.repo_base is None:
                raise optparse.OptionValueError(
                    'Need a target repo or --overlayed-repo that is a single '
                    'UnconfiguredTree for profile checks')
            profile_loc = os.path.join(values.repo_base, "profiles")
            if not os.path.isdir(profile_loc):
                raise optparse.OptionValueError(
                    "repo %r lacks a profiles directory" % (values.src_repo,))

        profile_loc = osutils.abspath(profile_loc)
        values.profile_func = currying.pre_curry(util.get_profile_from_path,
                                                 profile_loc)
        values.profile_base_dir = profile_loc

    def identify_profiles(self, pkg):
        return [(key, flags_dict) for key, flags_dict in
            self.profile_evaluate_dict.iteritems() if
            self.keywords_filter[key].match(pkg)]


class EvaluateDepSetAddon(base.Addon):

    # XXX QueryCache just for the query_caching_freq option, separate?
    required_addons = (ProfileAddon, QueryCacheAddon)

    feed_type = base.package_feed

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
        for key, flags_dict in profiles:
            for flags, profile_data in flags_dict.iteritems():
                # XXX optimize this
                empty_umd = None
                empty_ufd = None
                for umd, ufd, profile_name in profile_data:
                    ur = umd.get(pkey, None)
                    if ur is None:
                        if empty_umd is None:
                            tri_flags = empty_umd = diuse.intersection(flags[0])
                        else:
                            tri_flags = empty_umd
                    else:
                        tri_flags = diuse.intersection(chain(flags[0],
                            *[v for restrict, v in 
                                ur.iteritems()
                                if restrict.match(pkg)]))
                    ur = ufd.get(pkey, None)
                    if ur is None:
                        if empty_ufd is None:
                            set_flags = empty_ufd = diuse.intersection(flags[1])
                        else:
                            set_flags = empty_ufd
                    else:
                        set_flags = diuse.intersection(chain(flags[1],
                            *[v for restrict, v in
                                ur.iteritems()
                                if restrict.match(pkg)]))

                    collapsed.setdefault((tri_flags, 
                        set_flags), []).append((key, profile_name, 
                            self.profiles.profile_filters[key][profile_name]))

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
        if values.license_dir is None:
            if values.repo_base is None:
                raise optparse.OptionValueError(
                    'Need a target repo or --overlayed-repo that is a single '
                    'UnconfiguredTree for license checks')
            values.license_dir = os.path.join(values.repo_base, "licenses")
            if not os.path.isdir(values.license_dir):
                raise optparse.OptionValueError(
                    "repo %r doesn't have a license directory, you must specify "
                    "one via --license-dir or a different overlayed repo via "
                    "--overlayed-repo" % (values.src_repo,))
        else:
            if not os.path.isdir(values.license_dir):
                raise optparse.OptionValueError(
                    "--license-dir %r isn't a directory" % values.license_dir)
        values.license_dir = osutils.abspath(values.license_dir)
