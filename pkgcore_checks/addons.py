# Copyright: 2006 Marien Zwart <marienz@gentoo.org>
# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: GPL2


"""Addon functionality shared by multiple checkers."""


import optparse
from itertools import ifilter, ifilterfalse

from pkgcore_checks import base, util

from pkgcore.util import (
    demandload, currying, containers, mappings, iterables, lists)
demandload.demandload(
    globals(),
    'os '
    'errno '
    'pkgcore.util:osutils '
    'pkgcore.restrictions:packages,values '
    'pkgcore.ebuild:misc,domain,profiles '
    'pkgcore.util.file:read_dict '
    'pkgcore.log:logger '
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
        print values.query_caching_freq

    def __init__(self, options):
        base.Addon.__init__(self, options)
        self.query_cache = {}
        self.feed_type = self.options.query_caching_freq

    def feed(self, item, reporter):
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
        enabled = known_flags.intersection(self.forced_use.pull_data(pkg))
        immutable = enabled.union(ifilter(known_flags.__contains__,
            self.masked_use.pull_data(pkg)))
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
        values.profile_func = currying.pre_curry(profiles.OnDiskProfile,
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

                immutable_flags = misc.collapsed_restrict_to_data(
                    default_masked_use,
                    profile.masked_use.iteritems())
                enabled_flags = misc.collapsed_restrict_to_data(
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
        self.keywords_filter = mappings.OrderedDict(
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
        diuse = depset.known_conditionals
        collapsed = {}
        for profiles in profile_grps:
            immutables, enabled = profiles[0].identify_use(pkg, diuse)
            collapsed.setdefault((immutables, enabled), []).extend(profiles)

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


class UseAddon(base.Addon):

    def __init__(self, options):
        base.Addon.__init__(self, options)
        known_iuse = set()
        specific_iuse = []
        unstated_iuse = set()
        
        for profile_base in options.repo_bases:
            try:
                known_iuse.update(util.get_use_desc(
                    osutils.join(profile_base, 'profiles')))
            except IOError, ie:
                if ie.errno != errno.ENOENT:
                    raise

            try:
                for restricts_dict in \
                    util.get_use_local_desc(
                        osutils.join(profile_base, 'profiles')).itervalues():
                    specific_iuse.extend(restricts_dict.iteritems())

            except IOError, ie:
                if ie.errno != errno.ENOENT:
                    raise		

            use_expand_base = osutils.join(profile_base, "profiles", "desc")
            try:
                for entry in osutils.listdir_files(use_expand_base):
                    try:
                        estr = entry.rsplit(".", 1)[0].lower()+ "_"
                        unstated_iuse.update(estr + usef.strip() for usef in 
                            read_dict(osutils.join(use_expand_base, entry),
                                None).iterkeys())
                    except (IOError, OSError), ie:
                        if ie.errno != errno.EISDIR:
                            raise
                        del ie
            except (OSError, IOError), ie:
                if ie.errno != errno.ENOENT:
                    raise

        self.specific_iuse = misc.non_incremental_collapsed_restrict_to_data(
            ((packages.AlwaysTrue, known_iuse),), specific_iuse)
        known_iuse.update(x for y in specific_iuse for x in y[1])
        known_iuse.update(unstated_iuse)
        self.known_iuse = frozenset(known_iuse)
        unstated_iuse.update(util.get_repo_known_arches(
            osutils.join(profile_base, 'profiles')))
        self.unstated_iuse = frozenset(unstated_iuse)
        self.profile_bases = profile_base
        self.ignore = not (unstated_iuse or known_iuse)
        if self.ignore:
            logger.warn('disabling use/iuse validity checks since no usable '
                'use.desc, use.local.desc were found ')

    def allowed_iuse(self, pkg):
        return self.specific_iuse.pull_data(pkg)

    def get_filter(self):
        if self.ignore:
            return self.fake_iuse_validate
        return self.iuse_validate
        
    @staticmethod
    def fake_iuse_validate(klasses, pkg, seq, reporter):
        return iflatten_instance(seq, klasses)

    def iuse_validate(self, klasses, pkg, seq, reporter):
        skip_filter = (packages.Conditional,) + klasses
        unstated = set()
    
        stated = pkg.iuse
        i = iterables.expandable_chain(lists.iflatten_instance(seq,
                                                               skip_filter))
        for node in i:
            if isinstance(node, packages.Conditional):
                # invert it; get only whats not in pkg.iuse
                unstated.update(ifilterfalse(stated.__contains__,
                    node.restriction.vals))
                i.append(lists.iflatten_instance(node.payload, skip_filter))
                continue
            yield node

        # the valid_unstated_iuse filters out USE_EXPAND as long as
        # it's listed in a desc file
        unstated.difference_update(self.unstated_iuse)
        # hack, see bugs.gentoo.org 134994.
        unstated.difference_update(["bootstrap"])
        if unstated:
            if seq == pkg.depends:
                attr_name = "depends"
            elif seq == pkg.rdepends:
                attr_name = "rdepends"
            elif seq == pkg.post_rdepends:
                attr_name = "post_rdepends"
            elif seq == pkg.provides:
                attr_name = "provide"
            reporter.add_report(UnstatedIUSE(pkg, attr_name,
                unstated))


class UnstatedIUSE(base.Result):
    """pkg is reliant on conditionals that aren't in IUSE"""
    __slots__ = ("category", "package", "version", "attr", "flags")
    
    def __init__(self, pkg, attr, flags):
        base.Result.__init__(self)
        self._store_cpv(pkg)
        self.attr, self.flags = attr, tuple(flags)
    
    def to_str(self):
        return "%s/%s-%s: attr(%s) uses unstated flags [ %s ]" % \
        (self.category, self.package, self.version, self.attr,
            ", ".join(self.flags))

    def to_xml(self):
        return \
"""<check name="%s">
    <category>%s</category>
    <package>%s</package>
    <version>%s</version>
    <msg>attr %s uses unstead flags: %s"</msg>
</check>""" % (self.__class__.__name__, self.category, self.package,
    self.version, self.attr, ", ".join(self.flags))
