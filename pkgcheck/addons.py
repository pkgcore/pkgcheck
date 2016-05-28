# Copyright: 2006 Marien Zwart <marienz@gentoo.org>
# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: BSD/GPL2

"""Addon functionality shared by multiple checkers."""

from collections import OrderedDict, defaultdict
from functools import partial
from itertools import chain, ifilter, ifilterfalse, imap

from snakeoil.containers import ProtectedSet
from snakeoil.demandload import demandload
from snakeoil.iterables import expandable_chain
from snakeoil.osutils import abspath, listdir_files, pjoin
from snakeoil.sequences import iflatten_instance

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

    @classmethod
    def check_args(cls, parser, namespace):
        arches = namespace.selected_arches
        if arches is None:
            arches = ((), cls.default_arches)
        disabled, enabled = arches
        if not enabled:
            enabled = cls.default_arches
        namespace.arches = tuple(sorted(set(enabled).difference(set(disabled))))

    @classmethod
    def mangle_argparser(cls, parser):
        group = parser.add_argument_group('arches')
        group.add_argument(
            '-a', '--arches', dest='selected_arches', metavar='ARCHES',
            nargs=1, action='extend_comma_toggle',
            help='comma separated list of arches to enable/disable',
            docs="""
                Comma separated list of arches to enable and disable.

                To specify disabled arches prefix them with '-'. Note that when
                starting the argument list with a disabled arch an equals sign
                must be used, e.g. -a=-arch, otherwise the disabled arch
                argument is treated as an option.

                By default the enabled arch list is %s; however, stable-related
                checks (e.g. UnstableOnly) default to the set of arches having
                stable profiles in the target repo.
            """ % ", ".join(cls.default_arches))


class QueryCacheAddon(base.Template):

    priority = 1

    @staticmethod
    def mangle_argparser(parser):
        group = parser.add_argument_group('query caching')
        group.add_argument(
            '--reset-caching-per', dest='query_caching_freq',
            choices=('version', 'package', 'category'), default='package',
            help='control how often the cache is cleared '
                 '(version, package or category)')

    @staticmethod
    def check_args(parser, namespace):
        namespace.query_caching_freq = {
            'version': base.versioned_feed,
            'package': base.package_feed,
            'category': base.repository_feed,
            }[namespace.query_caching_freq]

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

    required_addons = (ArchesAddon,)

    @staticmethod
    def mangle_argparser(parser):
        group = parser.add_argument_group('profiles')
        group.add_argument(
            "--profiles-base", dest='profiles_dir', default=None,
            help="path to base profiles directory",
            docs="""
                The path to the base profiles directory. This will override the
                default usage of profiles bundled in the target repository;
                primarily for testing.
            """)
        group.add_argument(
            "--profiles-disable-deprecated", action='store_true',
            dest='profiles_ignore_deprecated',
            help="disable scanning of deprecated profiles")
        group.add_argument(
            '-p', '--profiles', action='extend_comma_toggle',
            dest='profiles',
            help='comma separated list of profiles to enable/disable',
            docs="""
                Comma separated list of profiles to enable and disable for
                scanning. Any profiles specified in this fashion will be the
                only profiles that get scanned, minus any disabled profiles. In
                addition, if no profiles are explicitly enabled via this
                option, all profiles will be scanned by default.

                To specify disabled profiles prefix them with '-'. Note that
                when starting the argument list with a disabled profile an
                equals sign must be used, e.g. -p=-path/to/profile, otherwise
                the disabled profile argument is treated as an option.

                The special keywords of stable, dev, and exp correspond to the
                lists of stable, development, and experimental profiles,
                respectively. Therefore, to only scan all stable profiles
                pass the 'stable' argument to --profiles.
            """)

    @staticmethod
    def check_args(parser, namespace):
        profiles_dir = getattr(namespace, "profiles_dir", None)
        if profiles_dir is not None:
            profiles_dir = abspath(profiles_dir)
            if not os.path.isdir(profiles_dir):
                raise parser.error(
                    "profile-base location %r doesn't exist/isn't a dir" % (
                        profiles_dir,))

        selected_profiles = namespace.profiles
        if selected_profiles is None:
            selected_profiles = ((), ())

        if profiles_dir:
            profiles_obj = repo_objs.BundledProfiles(profiles_dir)
        else:
            profiles_obj = namespace.target_repo.config.profiles

        def norm_name(s):
            """Expand status keywords and format paths."""
            if s in ('dev', 'exp', 'stable'):
                for x in profiles_obj.status_profiles(s):
                    yield x
            else:
                yield '/'.join(filter(None, s.split('/')))

        disabled, enabled = selected_profiles
        disabled = set(disabled)
        enabled = set(enabled)
        # remove profiles that are both enabled and disabled
        toggled = enabled.intersection(disabled)
        enabled = enabled.difference(toggled)
        disabled = disabled.difference(toggled)
        # expand status keywords, e.g. 'stable' -> set of stable profiles
        disabled = set(chain.from_iterable(imap(norm_name, disabled)))
        enabled = set(chain.from_iterable(imap(norm_name, enabled)))

        # If no profiles are enabled, then all are scanned except ones that are
        # explicitly disabled.
        if not enabled:
            enabled = {
                profile for profile, status in
                chain.from_iterable(profiles_obj.arch_profiles.itervalues())}

        profile_paths = enabled.difference(disabled)

        # We hold onto the profiles as we're going, due to the fact that
        # profile nodes are weakly cached; hold onto all for this loop, avoids
        # a lot of reparsing at the expense of slightly more memory usage
        # temporarily.
        cached_profiles = []

        arch_profiles = defaultdict(list)
        for profile_path in profile_paths:
            try:
                p = profiles_obj.create_profile(profile_path)
            except profiles.ProfileError as e:
                # Only throw errors if the profile was selected by the user, bad
                # repo profiles will be caught during repo metadata scans.
                if namespace.profiles is not None:
                    parser.error('invalid profile: %r: %s' % (e.path, e.error))
                continue
            if namespace.profiles_ignore_deprecated and p.deprecated:
                continue
            cached_profiles.append(p)
            if p.arch is None:
                raise profiles.ProfileError(
                    p.path, 'make.defaults',
                    "profile %s lacks arch settings, unable to use it" % profile_path)
            arch_profiles[p.arch].append((profile_path, p))

        namespace.arch_profiles = arch_profiles

    def __init__(self, options, *args):
        base.Addon.__init__(self, options)

        self.official_arches = options.target_repo.config.known_arches
        self.desired_arches = getattr(self.options, 'arches', None)
        if self.desired_arches is None or self.options.selected_arches is None:
            # copy it to be safe
            self.desired_arches = set(self.official_arches)

        self.global_insoluble = set()
        profile_filters = {}
        self.keywords_filter = {}

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

            for profile_name, profile in options.arch_profiles.get(k, []):
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

    def __iter__(self):
        """Iterate over all profile data objects."""
        return chain.from_iterable(self.profile_filters.itervalues())


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
        self.arches = set(options.arches)

        # use known stable arches if a custom arch set isn't specified
        selected_arches = getattr(options, 'selected_arches', None)
        if selected_arches is None:
            self.arches = options.src_repo.config.stable_arches


class LicenseAddon(base.Addon):

    @staticmethod
    def mangle_argparser(parser):
        parser.plugin.add_argument("--license-dir", help="filepath to license directory")

    @staticmethod
    def check_args(parser, namespace):
        namespace.license_dirs = []
        if namespace.license_dir is None:
            for repo_base in namespace.repo_bases:
                candidate = pjoin(repo_base, 'licenses')
                if os.path.isdir(candidate):
                    namespace.license_dirs.append(candidate)
            if not namespace.license_dirs:
                raise parser.error(
                    'No license dir detected, pick a target or overlayed repo '
                    'with a license dir or specify one with --license-dir.')
        else:
            if not os.path.isdir(namespace.license_dir):
                raise parser.error(
                    "--license-dir %r isn't a directory" % namespace.license_dir)
            namespace.license_dirs.append(abspath(namespace.license_dir))

    @property
    def licenses(self):
        o = getattr(self, "_licenses", None)
        if o is None:
            o = frozenset(iflatten_instance(
                listdir_files(x) for x in self.options.license_dirs))
            setattr(self, "_licenses", o)
        return o


class UnstatedIUSE(base.Error):
    """pkg is reliant on conditionals that aren't in IUSE"""
    __slots__ = ("category", "package", "version", "attr", "flags")

    threshold = base.versioned_feed

    def __init__(self, pkg, attr, flags):
        super(UnstatedIUSE, self).__init__()
        self._store_cpv(pkg)
        self.attr, self.flags = attr, tuple(flags)

    @property
    def short_desc(self):
        return "attr(%s) uses unstated flags [ %s ]" % \
            (self.attr, ', '.join(self.flags))


class UseAddon(base.Addon):

    required_addons = (ProfileAddon,)
    known_results = (UnstatedIUSE,)

    def __init__(self, options, profiles, silence_warnings=False):
        base.Addon.__init__(self, options)

        # common profile elements
        c_implicit_iuse = None

        for profile in profiles:
            if c_implicit_iuse is None:
                c_implicit_iuse = set(profile.iuse_effective)
            else:
                c_implicit_iuse.intersection_update(profile.iuse_effective)

        known_iuse = set()
        known_iuse_expand = set()

        known_iuse.update(x[1][0] for x in options.target_repo.config.use_desc)
        known_iuse_expand.update(x[1][0] for x in options.target_repo.config.use_expand_desc)

        self.collapsed_iuse = misc.non_incremental_collapsed_restrict_to_data(
            ((packages.AlwaysTrue, known_iuse),),
            ((packages.AlwaysTrue, known_iuse_expand),),
        )
        self.global_iuse = frozenset(known_iuse | known_iuse_expand)
        self.unstated_iuse = frozenset(c_implicit_iuse)
        self.ignore = not (c_implicit_iuse or known_iuse or known_iuse_expand)
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

        # implicit IUSE flags
        unstated.difference_update(self.unstated_iuse)
        if unstated:
            reporter.add_report(UnstatedIUSE(pkg, attr, unstated))
