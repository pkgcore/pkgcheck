# Copyright: 2006 Marien Zwart <marienz@gentoo.org>
# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: BSD/GPL2

"""Addon functionality shared by multiple checkers."""

from functools import partial
import optparse
from itertools import ifilter, ifilterfalse

from snakeoil.containers import ProtectedSet
from snakeoil.demandload import demandload
from snakeoil.iterables import expandable_chain
from snakeoil.lists import iflatten_instance
from snakeoil.mappings import OrderedDict
from snakeoil.osutils import abspath, listdir_files, pjoin

from pkgcheck import base

demandload(
    'os',
    'pkgcore.restrictions:packages,values',
    'pkgcore.ebuild:misc,domain,profiles,repo_objs',
    'pkgcore.log:logger',
)


class ArchesAddon(base.Addon):

    default_arches = tuple(sorted([
        "alpha", "amd64", "arm", "arm64", "hppa", "ia64", "m68k", "mips",
        "ppc", "ppc64", "s390", "sh", "sparc", "x86",
    ]))

    @staticmethod
    def _record_arches(option, opt_str, value, parser):
        setattr(parser.values, option.dest, tuple(value.split(",")))

    @classmethod
    def _disable_arches(cls, option, opt_str, value, parser):
        s = set(getattr(parser.values, 'arches', cls.default_arches))
        parser.values.arches = tuple(s.difference(value.split(",")))

    @classmethod
    def mangle_option_parser(cls, parser):
        parser.add_option(
            '-a', '--arches', action='callback', callback=cls._record_arches,
            type='string', default=cls.default_arches,
            help="comma separated list of what arches to run, defaults to %s "
            "-- note that stable-related checks (e.g. UnstableOnly) default "
            "to the set of arches having stable profiles in the target repo)"
            % ", ".join(cls.default_arches))
        parser.add_option(
            '--disable-arches', action='callback', callback=cls._disable_arches,
            type='string',
            help="comma separated list of arches to disable from the defaults")


class QueryCacheAddon(base.Template):

    priority = 1

    @staticmethod
    def mangle_option_parser(parser):
        group = parser.add_option_group('Query caching')
        group.add_option(
            '--reset-caching-per', action='store', type='choice',
            choices=('version', 'package', 'category'),
            dest='query_caching_freq', default='package',
            help='control how often the cache is cleared '
            '(version, package or category)')

    @staticmethod
    def check_values(values):
        values.query_caching_freq = {
            'version': base.versioned_feed,
            'package': base.package_feed,
            'category': base.repository_feed,
            }[values.query_caching_freq]

    def __init__(self, options):
        base.Addon.__init__(self, options)
        self.query_cache = {}
        # XXX this should be logging debug info
        self.feed_type = self.options.query_caching_freq

    def feed(self, item, reporter):
        # XXX as should this.
        self.query_cache.clear()


class profile_data(object):

    def __init__(self, profile_name, key, provides, vfilter,
                 iuse_effective, masked_use, forced_use, lookup_cache, insoluble):
        self.key = key
        self.name = profile_name
        self.provides_repo = provides
        self.provides_has_match = getattr(provides, 'has_match', provides.match)
        self.iuse_effective = iuse_effective
        self.masked_use = masked_use
        self.forced_use = forced_use
        self.cache = lookup_cache
        self.insoluble = insoluble
        self.visible = vfilter.match

    def identify_use(self, pkg, known_flags):
        # note we're trying to be *really* careful about not creating
        # pointless intermediate sets unless required
        # kindly don't change that in any modifications, it adds up.
        enabled = known_flags.intersection(self.forced_use.pull_data(pkg))
        immutable = enabled.union(
            ifilter(known_flags.__contains__, self.masked_use.pull_data(pkg)))
        force_disabled = self.masked_use.pull_data(pkg)
        if force_disabled:
            enabled = enabled.difference(force_disabled)
        return immutable, enabled


class ProfileAddon(base.Addon):

    @staticmethod
    def check_values(values):
        if values.profiles_enabled is None:
            values.profiles_enabled = []
        if values.profiles_disabled is None:
            values.profiles_disabled = []
        profiles_dir = getattr(values, "profiles_dir", None)

        if profiles_dir is not None:
            profiles_dir = abspath(profiles_dir)
            if not os.path.isdir(profiles_dir):
                raise optparse.OptionValueError(
                    "profile-base location %r doesn't exist/isn't a dir" % (
                        profiles_dir,))
        values.profiles_dir = profiles_dir

    @staticmethod
    def _record_profiles(option, opt_str, value, parser):
        setattr(parser.values, option.dest, tuple(value.split(",")))

    @classmethod
    def mangle_option_parser(cls, parser):
        group = parser.add_option_group('Profiles')
        group.add_option(
            "--profile-base", action='store', type='string',
            dest='profiles_dir', default=None,
            help="filepath to base profiles directory.  This will override the "
            "default usage of profiles bundled in the target repository; primarily "
            "for testing.")
        group.add_option(
            "--profile-disable-dev", action='store_true',
            default=False, dest='profile_ignore_dev',
            help="disable scanning of dev profiles")
        group.add_option(
            "--profile-disable-deprecated", action='store_true',
            default=False, dest='profile_ignore_deprecated',
            help="disable scanning of deprecated profiles")
        group.add_option(
            "--profile-disable-exp", action='store_true',
            default=False, dest='profile_ignore_exp',
            help="disable scanning of exp profiles")
        group.add_option(
            "--profile-disable-profiles-desc", action='store_false',
            default=True, dest='profiles_desc_enabled',
            help="disable loading profiles to scan from profiles.desc, you "
            "will want to enable profiles manually via --profile-enable")
        group.add_option(
            '--enable-profiles', action='callback', callback=cls._record_profiles,
            dest='profiles_enabled', type='string',
            help="comma separated list of profiles to scan")
        group.add_option(
            '--disable-profiles', action='callback', callback=cls._record_profiles,
            dest='profiles_disabled', type='string',
            help="comma separated list of profiles to ignore")

    def __init__(self, options, *args):
        base.Addon.__init__(self, options)

        norm_name = lambda s: '/'.join(filter(None, s.split('/')))

        if options.profiles_dir:
            profiles_obj = repo_objs.BundledProfiles(options.profiles_dir)
        else:
            profiles_obj = options.target_repo.config.profiles
        options.profiles_obj = profiles_obj
        disabled = set(norm_name(x) for x in options.profiles_disabled)
        enabled = set(
            x for x in (norm_name(y) for y in options.profiles_enabled)
            if x not in disabled)

        arch_profiles = {}
        if options.profiles_desc_enabled:
            for arch, profiles in options.profiles_obj.arch_profiles.iteritems():
                if options.profile_ignore_dev:
                    profiles = (x for x in profiles if x.status != 'dev')
                if options.profile_ignore_exp:
                    profiles = (x for x in profiles if x.status != 'exp')
                l = [x.profile for x in profiles if x.profile not in disabled]

                # wipe any enableds that are here already so we don't
                # get a profile twice
                enabled.difference_update(l)
                if l:
                    arch_profiles[arch] = l

        for x in enabled:
            p = options.profiles_obj.create_profile(x)
            arch = p.arch
            if arch is None:
                raise profiles.ProfileError(
                    p.path, 'make.defaults',
                    "profile %s lacks arch settings, unable to use it" % x)
            arch_profiles.setdefault(p.arch, []).append((x, p))

        self.official_arches = options.target_repo.config.known_arches

        self.desired_arches = getattr(self.options, 'arches', None)
        if self.desired_arches is None:
            # copy it to be safe
            self.desired_arches = set(self.official_arches)

        self.global_insoluble = set()
        profile_filters = {}
        self.keywords_filter = {}
        ignore_deprecated = self.options.profile_ignore_deprecated

        # we hold onto the profiles as we're going, due to the fact
        # profilenodes are weakly cached; hold onto all for this loop,
        # avoids a lot of reparsing at the expense of slightly more memory
        # temporarily.
        cached_profiles = []

        chunked_data_cache = {}

        for k in self.desired_arches:
            if k.lstrip("~") not in self.desired_arches:
                continue
            stable_key = k.lstrip("~")
            unstable_key = "~" + stable_key
            stable_r = packages.PackageRestriction("keywords",
                values.ContainmentMatch(stable_key))
            unstable_r = packages.PackageRestriction("keywords",
                values.ContainmentMatch(stable_key, unstable_key))

            default_masked_use = tuple(set(x for x in self.official_arches
                                           if x != stable_key))

            profile_filters.update({stable_key: [], unstable_key: []})
            for profile_name in arch_profiles.get(k, []):
                if not isinstance(profile_name, basestring):
                    profile_name, profile = profile_name
                else:
                    profile = options.profiles_obj.create_profile(profile_name)
                    cached_profiles.append(profile)
                if ignore_deprecated and profile.deprecated:
                    continue

                vfilter = domain.generate_filter(profile.masks, profile.unmasks)

                immutable_flags = profile.masked_use.clone(unfreeze=True)
                immutable_flags.add_bare_global((), default_masked_use)
                immutable_flags.optimize(cache=chunked_data_cache)
                immutable_flags.freeze()

                stable_immutable_flags = profile.stable_masked_use.clone(unfreeze=True)
                stable_immutable_flags.add_bare_global((), default_masked_use)
                stable_immutable_flags.optimize(cache=chunked_data_cache)
                stable_immutable_flags.freeze()

                enabled_flags = profile.forced_use.clone(unfreeze=True)
                enabled_flags.add_bare_global((), (stable_key,))
                enabled_flags.optimize(cache=chunked_data_cache)
                enabled_flags.freeze()

                stable_enabled_flags = profile.stable_forced_use.clone(unfreeze=True)
                stable_enabled_flags.add_bare_global((), (stable_key,))
                stable_enabled_flags.optimize(cache=chunked_data_cache)
                stable_enabled_flags.freeze()

                # used to interlink stable/unstable lookups so that if
                # unstable says it's not visible, stable doesn't try
                # if stable says something is visible, unstable doesn't try.
                stable_cache = set()
                unstable_insoluble = ProtectedSet(self.global_insoluble)

                # few notes.  for filter, ensure keywords is last, on the
                # offchance a non-metadata based restrict foregos having to
                # access the metadata.
                # note that the cache/insoluble are inversly paired;
                # stable cache is usable for unstable, but not vice versa.
                # unstable insoluble is usable for stable, but not vice versa

                profile_filters[stable_key].append(profile_data(
                    profile_name, stable_key,
                    profile.provides_repo,
                    packages.AndRestriction(vfilter, stable_r),
                    profile.iuse_effective,
                    stable_immutable_flags, stable_enabled_flags,
                    stable_cache,
                    ProtectedSet(unstable_insoluble)))

                profile_filters[unstable_key].append(profile_data(
                    profile_name, unstable_key,
                    profile.provides_repo,
                    packages.AndRestriction(vfilter, unstable_r),
                    profile.iuse_effective,
                    immutable_flags, enabled_flags,
                    ProtectedSet(stable_cache),
                    unstable_insoluble))

            self.keywords_filter[stable_key] = stable_r
            self.keywords_filter[unstable_key] = packages.PackageRestriction(
                "keywords",
                values.ContainmentMatch(unstable_key))

        profile_evaluate_dict = {}
        for key, profile_list in profile_filters.iteritems():
            similar = profile_evaluate_dict[key] = []
            for profile in profile_list:
                for existing in similar:
                    if existing[0].masked_use == profile.masked_use and \
                            existing[0].forced_use == profile.forced_use:
                        existing.append(profile)
                        break
                else:
                    similar.append([profile])

        self.profile_evaluate_dict = profile_evaluate_dict
        self.arch_profiles = arch_profiles
        self.keywords_filter = OrderedDict(
            (k, self.keywords_filter[k])
            for k in sorted(self.keywords_filter))
        self.profile_filters = profile_filters

    def identify_profiles(self, pkg):
        # yields groups of profiles; the 'groups' are grouped by the ability to share
        # the use processing across each of 'em.
        l = []
        for key in set(pkg.keywords):
            profile_grps = self.profile_evaluate_dict.get(key)
            if profile_grps is None:
                continue
            for profiles in profile_grps:
                l2 = [x for x in profiles if x.visible(pkg)]
                if not l2:
                    continue
                l.append(l2)
        return l


class EvaluateDepSetAddon(base.Template):

    required_addons = (ProfileAddon,)
    feed_type = base.versioned_feed
    priority = 1

    def __init__(self, options, profiles):
        base.Addon.__init__(self, options)
        self.pkg_evaluate_depsets_cache = {}
        self.pkg_profiles_cache = {}
        self.profiles = profiles

    def feed(self, item, reporter):
        self.pkg_evaluate_depsets_cache.clear()
        self.pkg_profiles_cache.clear()

    def collapse_evaluate_depset(self, pkg, attr, depset):
        depset_profiles = self.pkg_evaluate_depsets_cache.get((pkg, attr))
        if depset_profiles is None:
            depset_profiles = self.identify_common_depsets(pkg, depset)
            self.pkg_evaluate_depsets_cache[(pkg, attr)] = depset_profiles
        return depset_profiles

    def identify_common_depsets(self, pkg, depset):
        profile_grps = self.pkg_profiles_cache.get(pkg, None)
        if profile_grps is None:
            profile_grps = self.profiles.identify_profiles(pkg)
            self.pkg_profiles_cache[pkg] = profile_grps

        # strip use dep defaults so known flags get identified correctly
        diuse = frozenset([x[:-3] if x[-1] == ')' else x
                          for x in depset.known_conditionals])
        collapsed = {}
        for profiles in profile_grps:
            immutable, enabled = profiles[0].identify_use(pkg, diuse)
            collapsed.setdefault((immutable, enabled), []).extend(profiles)

        return [(depset.evaluate_depset(k[1], tristate_filter=k[0]), v)
                for k, v in collapsed.iteritems()]


class StableCheckAddon(base.Template):

    """Check relating to stable arches by default."""

    def __init__(self, options, *args):
        super(StableCheckAddon, self).__init__(self, options)

        # use known stable arches if a custom arch set isn't specified
        self.arches = set(options.arches)
        if self.arches == set(ArchesAddon.default_arches):
            self.arches = options.src_repo.config.stable_arches


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
                candidate = pjoin(repo_base, 'licenses')
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
            values.license_dirs.append(abspath(values.license_dir))

    @property
    def licenses(self):
        o = getattr(self, "_licenses", None)
        if o is None:
            o = frozenset(iflatten_instance(
                listdir_files(x) for x in self.options.license_dirs))
            setattr(self, "_licenses", o)
        return o


class UnstatedIUSE(base.Result):
    """pkg is reliant on conditionals that aren't in IUSE"""
    __slots__ = ("category", "package", "version", "attr", "flags")

    threshold = base.versioned_feed

    def __init__(self, pkg, attr, flags):
        base.Result.__init__(self)
        self._store_cpv(pkg)
        self.attr, self.flags = attr, tuple(flags)

    @property
    def short_desc(self):
        return "attr(%s) uses unstated flags [ %s ]" % \
            (self.attr, ', '.join(self.flags))


class UseAddon(base.Addon):

    known_results = (UnstatedIUSE,)

    def __init__(self, options, silence_warnings=False):
        base.Addon.__init__(self, options)
        known_iuse = set()
        unstated_iuse = set()
        arches = set()

        known_iuse.update(x[1][0] for x in options.target_repo.config.use_desc)
        arches.update(options.target_repo.config.known_arches)
        unstated_iuse.update(x[1][0] for x in options.target_repo.config.use_expand_desc)

        self.collapsed_iuse = misc.non_incremental_collapsed_restrict_to_data(
            ((packages.AlwaysTrue, known_iuse),),
            ((packages.AlwaysTrue, unstated_iuse),),
        )
        self.global_iuse = frozenset(known_iuse)
        unstated_iuse.update(arches)
        self.unstated_iuse = frozenset(unstated_iuse)
        self.ignore = not (unstated_iuse or known_iuse)
        if self.ignore and not silence_warnings:
            logger.warn('disabling use/iuse validity checks since no usable '
                        'use.desc, use.local.desc were found ')

    def allowed_iuse(self, pkg):
        return self.collapsed_iuse.pull_data(pkg).union(pkg.local_use)

    def get_filter(self, attr_name=None):
        if self.ignore:
            return self.fake_use_validate
        if attr_name is not None:
            return partial(self.use_validate, attr=attr_name)
        return self.use_validate

    @staticmethod
    def fake_use_validate(klasses, pkg, seq, reporter, attr=None):
        return iflatten_instance(seq, klasses)

    def use_validate(self, klasses, pkg, seq, reporter, attr=None):
        skip_filter = (packages.Conditional,) + klasses
        unstated = set()

        stated = pkg.iuse_stripped
        i = expandable_chain(iflatten_instance(seq, skip_filter))
        for node in i:
            if isinstance(node, packages.Conditional):
                # invert it; get only whats not in pkg.iuse
                unstated.update(ifilterfalse(stated.__contains__, node.restriction.vals))
                i.append(iflatten_instance(node.payload, skip_filter))
                continue
            yield node

        # the valid_unstated_iuse filters out USE_EXPAND as long as
        # it's listed in a desc file
        unstated.difference_update(self.unstated_iuse)
        # hack, see bugs.gentoo.org 134994; same goes for prefix
        unstated.difference_update(["bootstrap", "prefix"])
        if unstated:
            reporter.add_report(UnstatedIUSE(pkg, attr, unstated))
