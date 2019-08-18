import argparse
import itertools
import os
import shutil

from pkgcore.ebuild import repo_objs, repository
from pkgcore.restrictions import packages
from pkgcore.util import commandline
from snakeoil.fileutils import write_file
from snakeoil.osutils import pjoin, ensure_dirs

from pkgcheck import addons, base

from .misc import FakePkg, FakeProfile, Options, Tmpdir


class ArgparseCheck(object):

    def process_check(self, args, preset_values={},
                      namespace=None, addon_kls=None, **settings):
        addon_kls = addon_kls if addon_kls is not None else self.addon_kls
        p = commandline.ArgumentParser(domain=False, color=False)
        p.plugin = p.add_argument_group('plugin options')
        addon_kls.mangle_argparser(p)
        args, unknown_args = p.parse_known_args(args, namespace)
        assert unknown_args == []
        orig_out, orig_err = None, None
        for attr, val in preset_values.items():
            setattr(args, attr, val)
        addon_kls.check_args(p, args)
        for attr, val in settings.items():
            assert getattr(args, attr) == val, (
                f"for args {args!r}, {attr} must be {val!r}, got {getattr(args, attr)!r}")
        return args


class TestArchesAddon(ArgparseCheck):

    addon_kls = addons.ArchesAddon

    def test_opts(self):
        for arg in ('-a', '--arches'):
            self.process_check([arg, 'x86'], arches=('x86',))
            self.process_check([arg, 'x86,ppc'], arches=('ppc', 'x86'))
            self.process_check([arg, 'x86,ppc,-x86'], arches=('ppc',))

    def test_default(self):
        self.process_check([], arches=())


class TestQueryCacheAddon(ArgparseCheck):

    addon_kls = addons.QueryCacheAddon
    default_feed = base.package_feed

    def test_opts(self):
        for val, ret in (('version', base.versioned_feed),
                         ('package', base.package_feed),
                         ('category', base.repository_feed)):
            self.process_check(['--reset-caching-per', val], query_caching_freq=ret)

    def test_default(self):
        self.process_check([], query_caching_freq=self.default_feed)

    def test_feed(self):
        options = self.process_check([])
        check = self.addon_kls(options)
        check.start()
        assert check.feed_type == self.default_feed
        check.query_cache['foo'] = 'bar'
        check.feed(None)
        assert not check.query_cache


class Test_profile_data(object):

    def assertResults(self, profile, known_flags, required_immutable,
                      required_forced, cpv="dev-util/diffball-0.1",
                      key_override=None, data_override=None):
        if key_override is None:
            key = profile.key
        profile_data = addons.ProfileData(
            "test-profile", key_override,
            profile.provides_repo,
            packages.AlwaysFalse, profile.iuse_effective,
            profile.use, profile.pkg_use, profile.masked_use, profile.forced_use, {}, set(),
            'stable', False)
        pkg = FakePkg(cpv, data=data_override)
        immutable, enabled = profile_data.identify_use(pkg, set(known_flags))
        assert immutable == set(required_immutable)
        assert enabled == set(required_forced)

    def test_identify_use(self):
        profile = FakeProfile()
        self.assertResults(profile, [], [], [])

        profile = FakeProfile(masked_use={"dev-util/diffball": ["lib"]})
        self.assertResults(profile, [], [], [])
        self.assertResults(profile, ["lib"], ["lib"], [])

        profile = FakeProfile(masked_use={"=dev-util/diffball-0.2": ["lib"]})
        self.assertResults(profile, ["lib"], [], [])

        profile = FakeProfile(masked_use={"dev-util/foon": ["lib"]})
        self.assertResults(profile, ["lib"], [], [])

        profile = FakeProfile(forced_use={"dev-util/diffball": ["lib"]})
        self.assertResults(profile, [], [], [])
        self.assertResults(profile, ["lib", "bar"], ["lib"], ["lib"])

        profile = FakeProfile(
            forced_use={"dev-util/diffball": ["lib"]},
            masked_use={"dev-util/diffball": ["lib"]})
        self.assertResults(profile, [], [], [])
        # check that masked use wins out over forced.
        self.assertResults(profile, ["lib", "bar"], ["lib"], [])

        profile = FakeProfile(
            forced_use={"dev-util/diffball": ["lib"]},
            masked_use={"dev-util/diffball": ["lib"]})
        self.assertResults(profile, [], [], [])
        # check that masked use wins out over forced.
        self.assertResults(profile, ["lib", "bar"], ["lib"], [])


class ProfilesMixin(ArgparseCheck, Tmpdir):

    addon_kls = addons.ProfileAddon

    def mk_profiles(self, profiles, base='profiles', arches=None):
        os.mkdir(pjoin(self.dir, 'metadata'))
        # write empty masters to suppress warnings
        write_file(pjoin(self.dir, 'metadata', 'layout.conf'), 'w', 'masters=')

        loc = pjoin(self.dir, base)
        os.mkdir(loc)
        if base != 'profiles':
            # write empty masters to suppress warnings
            os.mkdir(pjoin(loc, 'metadata'))
            write_file(pjoin(loc, 'metadata', 'layout.conf'), 'w', 'masters=')
        for profile in profiles:
            assert ensure_dirs(pjoin(loc, profile)), f"failed creating profile {profile!r}"
        if arches is None:
            arches = set(val[0] for val in profiles.values())
        write_file(pjoin(loc, 'arch.list'), 'w', "\n".join(arches))
        write_file(pjoin(loc, 'repo_name'), 'w', 'testing')
        write_file(pjoin(loc, 'eapi'), 'w', '5')
        with open(pjoin(loc, 'profiles.desc'), 'w') as fd:
            for profile, vals in profiles.items():
                l = len(vals)
                if l == 1 or not vals[1]:
                    fd.write(f"{vals[0]}\t{profile}\tstable\n")
                else:
                    fd.write(f"{vals[0]}\t{profile}\t{vals[1]}\n")
                if l == 3 and vals[2]:
                    with open(pjoin(loc, profile, 'deprecated'), 'w') as f:
                        f.write("foon\n#dar\n")
                with open(pjoin(loc, profile, 'make.defaults'), 'w') as f:
                    f.write(f"ARCH={vals[0]}\n")
                with open(pjoin(loc, profile, 'eapi'), 'w') as f:
                    f.write('5')

    def process_check(self, profiles_base, *args, **kwds):
        namespace = argparse.Namespace()
        if profiles_base is None:
            repo_config = repo_objs.RepoConfig(location=self.dir)
        else:
            repo_config = repo_objs.RepoConfig(location=profiles_base, profiles_base='.')
        namespace.target_repo = repository.UnconfiguredTree(
            repo_config.location, repo_config=repo_config)
        namespace.search_repo = Options()
        namespace.profile_cache = False
        options = ArgparseCheck.process_check(self, namespace=namespace, *args, **kwds)
        return options


class TestProfileAddon(ProfilesMixin):

    def assertProfiles(self, check, key, *profile_names):
        assert (
            sorted(x.name for y in check.profile_evaluate_dict[key] for x in y) ==
            sorted(profile_names))

    def test_defaults(self):
        self.mk_profiles({
            "profile1": ["x86"],
            "profile1/2": ["x86"]},
            base='profiles')
        options = self.process_check(None, [], profiles=None)
        # override the default
        check = self.addon_kls(options)
        assert sorted(check.official_arches) == ['x86']
        assert sorted(check.desired_arches) == ['x86']
        assert sorted(check.profile_evaluate_dict) == ['x86', '~x86']
        self.assertProfiles(check, 'x86', 'profile1', 'profile1/2')

    def test_fallback_defaults(self):
        self.mk_profiles({
            "default-linux/dep": ["x86", False, True],
            "default-linux/dev": ["x86", "dev"],
            "default-linux/exp": ["x86", "exp"],
            "default-linux": ["x86"]},
            base='foo')
        options = self.process_check(pjoin(self.dir, 'foo'), ['--profiles=stable,-stable'])
        check = self.addon_kls(options)
        self.assertProfiles(check, 'x86', 'default-linux', 'default-linux/dev', 'default-linux/exp')

    def test_profiles_base(self):
        self.mk_profiles({
            "default-linux/dep": ["x86", False, True],
            "default-linux": ["x86", "dev"],
            "default-linux/x86": ["x86"]},
            base='foo')
        options = self.process_check(pjoin(self.dir, 'foo'), [])
        check = self.addon_kls(options)
        self.assertProfiles(check, 'x86', 'default-linux', 'default-linux/x86')

    def test_enable_stable(self):
        self.mk_profiles({
            "default-linux/dep": ["x86", False, True],
            "default-linux/dev": ["x86", "dev"],
            "default-linux/exp": ["x86", "exp"],
            "default-linux": ["x86"]},
            base='foo')
        options = self.process_check(pjoin(self.dir, 'foo'), ['--profiles=stable'])
        check = self.addon_kls(options)
        self.assertProfiles(check, 'x86', 'default-linux')

    def test_disable_stable(self):
        self.mk_profiles({
            "default-linux/dep": ["x86", False, True],
            "default-linux/dev": ["x86", "dev"],
            "default-linux/exp": ["x86", "exp"],
            "default-linux": ["x86"]},
            base='foo')
        options = self.process_check(pjoin(self.dir, 'foo'), ['--profiles=-stable'])
        check = self.addon_kls(options)
        self.assertProfiles(check, 'x86', 'default-linux/dev', 'default-linux/exp')

    def test_enable_dev(self):
        self.mk_profiles({
            "default-linux/dep": ["x86", False, True],
            "default-linux/dev": ["x86", "dev"],
            "default-linux/x86": ["x86"]},
            base='foo')
        options = self.process_check(pjoin(self.dir, 'foo'), ['--profiles=dev'])
        check = self.addon_kls(options)
        self.assertProfiles(check, 'x86', 'default-linux/dev')

    def test_disable_dev(self):
        self.mk_profiles({
            "default-linux/dep": ["x86", False, True],
            "default-linux/dev": ["x86", "dev"],
            "default-linux/x86": ["x86"]},
            base='foo')
        options = self.process_check(pjoin(self.dir, 'foo'), ['--profiles=-dev'])
        check = self.addon_kls(options)
        self.assertProfiles(check, 'x86', 'default-linux/x86')

    def test_enable_exp(self):
        self.mk_profiles({
            "default-linux/dep": ["x86", False, True],
            "default-linux/exp": ["x86", "exp"],
            "default-linux/x86": ["x86"]},
            base='foo')
        options = self.process_check(pjoin(self.dir, 'foo'), ['--profiles=exp'])
        check = self.addon_kls(options)
        self.assertProfiles(check, 'x86', 'default-linux/exp')

    def test_disable_exp(self):
        self.mk_profiles({
            "default-linux/dep": ["x86", False, True],
            "default-linux/exp": ["x86", "exp"],
            "default-linux/x86": ["x86"]},
            base='foo')
        options = self.process_check(pjoin(self.dir, 'foo'), ['--profiles=-exp'])
        check = self.addon_kls(options)
        self.assertProfiles(check, 'x86', 'default-linux/x86')

    def test_enable_deprecated(self):
        self.mk_profiles({
            "default-linux/dep": ["x86", False, True],
            "default-linux/x86": ["x86"]},
            base='foo')
        options = self.process_check(
            pjoin(self.dir, 'foo'), ['--profiles=deprecated'])
        check = self.addon_kls(options)
        self.assertProfiles(check, 'x86', 'default-linux/dep')

    def test_disable_deprecated(self):
        self.mk_profiles({
            "default-linux/dep": ["x86", False, True],
            "default-linux/x86": ["x86"]},
            base='foo')
        options = self.process_check(
            pjoin(self.dir, 'foo'), ['--profiles=-deprecated'])
        check = self.addon_kls(options)
        self.assertProfiles(check, 'x86', 'default-linux/x86')

    def test_profile_enable(self):
        self.mk_profiles({
            "default-linux/dep": ["x86", False, True],
            "default-linux": ["x86"],
            "default-linux/x86": ["x86"]},
            base='foo')
        options = self.process_check(pjoin(self.dir, 'foo'), ['--profiles', 'default-linux/x86'])
        check = self.addon_kls(options)
        self.assertProfiles(check, 'x86', 'default-linux/x86')

    def test_profile_disable(self):
        self.mk_profiles({
            "default-linux/dep": ["x86", False, True],
            "default-linux": ["x86"],
            "default-linux/x86": ["x86"]},
            base='foo')
        options = self.process_check(pjoin(self.dir, 'foo'), ['--profiles=-default-linux/x86'])
        check = self.addon_kls(options)
        self.assertProfiles(check, 'x86', 'default-linux')

    def test_identify_profiles(self):
        self.mk_profiles({
            'default-linux': ['x86'],
            'default-linux/x86': ["x86"],
            'default-linux/ppc': ['ppc']},
            base='foo')

        counter = itertools.count()

        def run_check(*args):
            # create a fresh tree for the profile work everytime.
            # do this, so that it's always a unique pathway- this sidesteps
            # any potential issues of ProfileNode instance caching.
            path = pjoin(self.dir, 'foo', str(next(counter)))
            shutil.copytree(pjoin(self.dir, 'foo'), path, symlinks=True)
            return self.process_check(path, list(args))

        options = run_check()
        check = self.addon_kls(options)
        # assert they're collapsed properly.
        self.assertProfiles(check, 'x86', 'default-linux', 'default-linux/x86')
        assert len(check.profile_evaluate_dict['x86']) == 1
        assert len(check.profile_evaluate_dict['x86'][0]) == 2
        self.assertProfiles(check, 'ppc', 'default-linux/ppc')

        l = check.identify_profiles(FakePkg("d-b/ab-1", data={'KEYWORDS': 'x86'}))
        assert len(l) == 2, f"checking for profile collapsing: {l!r}"
        assert len(l[0]) == 2, f"checking for proper # of profiles: {l[0]!r}"
        assert sorted(x.name for x in l[0]) == sorted(['default-linux', 'default-linux/x86'])

        # check arch vs ~arch runs (i.e. arch KEYWORDS should also trigger ~arch runs)
        l = check.identify_profiles(FakePkg("d-b/ab-1", data={'KEYWORDS': '~x86'}))
        assert len(l) == 1, f"checking for profile collapsing: {l!r}"
        assert len(l[0]) == 2, f"checking for proper # of profiles: {l[0]!r}"
        assert sorted(x.name for x in l[0]) == sorted(['default-linux', 'default-linux/x86'])

        # check keyword collapsing
        l = check.identify_profiles(FakePkg("d-b/ab-2", data={'KEYWORDS': 'ppc'}))
        assert len(l) == 2, f"checking for profile collapsing: {l!r}"
        assert len(l[0]) == 1, f"checking for proper # of profiles: {l[0]!r}"
        assert l[0][0].name == 'default-linux/ppc'

        l = check.identify_profiles(FakePkg("d-b/ab-2", data={'KEYWORDS': 'foon'}))
        assert len(l) == 0, f"checking for profile collapsing: {l!r}"

        # test collapsing reusing existing profile layout
        with open(pjoin(self.dir, 'foo', 'default-linux', 'use.mask'), 'w') as f:
            f.write("lib")
        options = run_check()
        check = self.addon_kls(options)
        self.assertProfiles(check, 'x86', 'default-linux', 'default-linux/x86')
        assert len(check.profile_evaluate_dict['x86']) == 2

        with open(pjoin(self.dir, 'foo', 'default-linux', 'x86', 'use.mask'), 'w') as f:
            f.write("lib")
        options = run_check()
        check = self.addon_kls(options)
        self.assertProfiles(check, 'x86', 'default-linux', 'default-linux/x86')
        assert len(check.profile_evaluate_dict['x86']) == 1

        # test collapsing reusing existing profile layout
        with open(pjoin(self.dir, 'foo', 'default-linux', 'use.force'), 'w') as f:
            f.write("foo")
        options = run_check()
        check = self.addon_kls(options)
        self.assertProfiles(check, 'x86', 'default-linux', 'default-linux/x86')
        assert len(check.profile_evaluate_dict['x86']) == 2

        with open(pjoin(self.dir, 'foo', 'default-linux', 'x86', 'use.force'), 'w') as f:
            f.write("foo")
        options = run_check()
        check = self.addon_kls(options)
        self.assertProfiles(check, 'x86', 'default-linux', 'default-linux/x86')
        assert len(check.profile_evaluate_dict['x86']) == 1


class TestEvaluateDepSetAddon(ProfilesMixin):

    addon_kls = addons.EvaluateDepSetAddon

    def get_check(self, *profiles):
        # basically carefully tweak profileaddon to get ourself an instance
        # since evaluate relies on it.
        profile_options = self.process_check(
            None, [f"--profiles={','.join(profiles)}"], addon_kls=addons.ProfileAddon)
        profile_check = addons.ProfileAddon(profile_options)

        # now we're good to go.
        return self.addon_kls(profile_options, profile_check)

    def test_it(self):
        with open(pjoin(self.dir, "arch.list"), "w") as f:
            f.write("\n".join(('amd64', 'ppc', 'x86')))

        self.mk_profiles({
            "1": ["x86"],
            "2": ["x86"],
            "3": ["ppc"]},
            base='profiles')

        with open(pjoin(self.dir, 'profiles', '1', 'package.use.stable.mask'), 'w') as f:
            f.write('dev-util/diffball foo')
        with open(pjoin(self.dir, 'profiles', '2', 'package.use.stable.force'), 'w') as f:
            f.write('=dev-util/diffball-0.1 bar foo')
        with open(pjoin(self.dir, 'profiles', '3', 'package.use.stable.force'), 'w') as f:
            f.write('dev-util/diffball bar foo')

        check = self.get_check('1', '2', '3')

        def get_rets(ver, attr, KEYWORDS="x86", **data):
            data["KEYWORDS"] = KEYWORDS
            pkg = FakePkg(f"dev-util/diffball-{ver}", data=data)
            return check.collapse_evaluate_depset(pkg, attr, getattr(pkg, attr))

        # few notes... for ensuring proper profiles came through, use
        # sorted(x.name for x in blah); reasoning is that it will catch
        # if duplicates come through, *and* ensure proper profile collapsing

        # shouldn't return anything due to no profiles matching the keywords.
        assert get_rets("0.0.1", "depend", KEYWORDS="foon") == []
        l = get_rets("0.0.2", "depend")
        assert len(l) == 1, f"must collapse all profiles down to one run: got {l!r}"
        assert len(l[0][1]) == 4, "must have four runs, (arch and ~arch for each profile)"
        assert sorted(set(x.name for x in l[0][1])) == ['1', '2'], f"must have two profiles: got {l!r}"
        assert l[0][1][0].key == 'x86'
        assert l[0][1][1].key == 'x86'

        l = get_rets(
            "0.1", "rdepend",
            RDEPEND="x? ( dev-util/confcache ) foo? ( dev-util/foo ) "
                    "bar? ( dev-util/bar ) !bar? ( dev-util/nobar ) x11-libs/xserver"
        )

        assert len(l) == 3, f"must collapse all profiles down to 3 runs: got {l!r}"

        # ordering is potentially random; thus pull out which depset result is
        # which based upon profile
        l1 = [x for x in l if x[1][0].name == '1'][0]
        l2 = [x for x in l if x[1][0].name == '2'][0]

        assert (
            set(str(l1[0]).split()) ==
            set(['dev-util/confcache', 'dev-util/bar', 'dev-util/nobar',
                'x11-libs/xserver']))

        assert (
            set(str(l2[0]).split()) ==
            set(['dev-util/confcache', 'dev-util/foo', 'dev-util/bar',
                'x11-libs/xserver']))

        # test feed wiping, using an empty depset; if it didn't clear, then
        # results from a pkg/attr tuple from above would come through rather
        # then an empty.
        check.feed(None)
        l = get_rets("0.1", "rdepend")
        assert len(l) == 1, f"feed didn't clear the cache- should be len 1: {l!r}"

        check.feed(None)

        # ensure it handles arch right.
        l = get_rets("0", "depend", KEYWORDS="ppc x86")
        assert len(l) == 1, f"should be len 1, got {l!r}"
        assert sorted(set(x.name for x in l[0][1])) == ["1", "2", "3"], (
            f"should have three profiles of 1-3, got {l[0][1]!r}")

        # ensure it's caching profile collapsing, iow, keywords for same ver
        # that's partially cached (single attr at least) should *not* change
        # things.

        l = get_rets("0", "depend", KEYWORDS="ppc")
        assert sorted(set(x.name for x in l[0][1])) == ['1', '2', '3'], (
            f"should have 3 profiles, got {l[0][1]!r}\nthis indicates it's "
            "re-identifying profiles every invocation, which is unwarranted ")

        l = get_rets("1", "depend", KEYWORDS="ppc x86",
            DEPEND="ppc? ( dev-util/ppc ) !ppc? ( dev-util/x86 )")
        assert len(l) == 2, f"should be len 2, got {l!r}"

        # same issue, figure out what is what
        l1 = [x[1] for x in l if str(x[0]).strip() == "dev-util/ppc"][0]
        l2 = [x[1] for x in l if str(x[0]).strip() == "dev-util/x86"][0]

        assert sorted(set(x.name for x in l1)) == ["3"]
        assert sorted(set(x.name for x in l2)) == ["1", "2"]


class TestUseAddon(ArgparseCheck, Tmpdir):

    addon_kls = addons.UseAddon

    def test_it(self):
        pass
    test_it.skip = "todo"
