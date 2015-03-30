# Copyright: 2007 Brian Harring <ferringb@gmail.com>
# License: BSD/GPL2

import itertools
import optparse
import os
import shutil
import sys

from pkgcore.ebuild import repo_objs
from pkgcore.restrictions import packages
from pkgcore.test import TestCase
from snakeoil.fileutils import write_file
from snakeoil.osutils import pjoin, ensure_dirs
from snakeoil.test import mixins

from pkgcheck import addons, base
from pkgcheck.test.misc import FakePkg, FakeProfile, Options


class exit_exception(Exception):
    def __init__(self, *args):
        self.args = args


class parser(optparse.OptionParser):

    def exit(self, *args):
        raise exit_exception(*args)


class base_test(TestCase):

    addon_kls = None

    def process_check(self, args, silence=False, preset_values={}, **settings):
        p = parser()
        self.addon_kls.mangle_option_parser(p)
        options, ret_args = p.parse_args(args)
        self.assertFalse(ret_args, msg="%r args were left after processing %r" %
            (ret_args, args))
        orig_out, orig_err = None, None
        for attr, val in preset_values.iteritems():
            setattr(options, attr, val)
        try:
                if silence:
                    orig_out = sys.stdout
                    orig_err = sys.stderr
                    sys.stdout = sys.stderr = open("/dev/null", "w")
                self.addon_kls.check_values(options)
        finally:
            if silence:
                if orig_out:
                    sys.stdout.close()
                    sys.stdout = orig_out
                if orig_err:
                    sys.stderr.close()
                    sys.stderr = orig_err

        for attr, val in settings.iteritems():
            self.assertEqual(getattr(options, attr), val,
                msg="for args %r, %s must be %r, got %r" % (args, attr, val,
                    getattr(options, attr)))
        return options


class TestArchesAddon(base_test):

    addon_kls = addons.ArchesAddon

    def test_opts(self):
        for arg in ('-a', '--arches'):
            self.process_check([arg, 'x86'], arches=('x86',))
            self.process_check([arg, 'x86,ppc'], arches=('x86', 'ppc'))

    def test_default(self):
        self.process_check([], arches=self.addon_kls.default_arches)


class TestQueryCacheAddon(base_test):

    addon_kls = addons.QueryCacheAddon
    default_feed = base.package_feed

    def test_opts(self):
        for val, ret in (('version', base.versioned_feed),
                         ('package', base.package_feed),
                         ('category', base.repository_feed)):
            self.process_check(
                ['--reset-caching-per', val],
                query_caching_freq=ret, silence=True)

    def test_default(self):
        self.process_check(
            [], silence=True, query_caching_freq=self.default_feed)

    def test_feed(self):
        options = self.process_check([], silence=True)
        check = self.addon_kls(options)
        check.start()
        self.assertEqual(check.feed_type, self.default_feed)
        check.query_cache["boobies"] = "hooray for"
        check.feed(None, None)
        self.assertFalse(check.query_cache)


class Test_profile_data(TestCase):

    def assertResults(self, profile, known_flags, required_immutable,
                      required_forced, cpv="dev-util/diffball-0.1",
                      key_override=None, data_override=None):
        if key_override is None:
            key = profile.arch
        profile_data = addons.profile_data(
            "test-profile", key_override,
            profile.provides_repo,
            packages.AlwaysFalse, profile.iuse_effective,
            profile.masked_use, profile.forced_use, {}, set())
        pkg = FakePkg(cpv, data=data_override)
        immutable, enabled = profile_data.identify_use(pkg, set(known_flags))
        self.assertEqual(immutable, set(required_immutable))
        self.assertEqual(enabled, set(required_forced))

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


class QuietRepoConfig(repo_objs.RepoConfig):

    def load_config(self):
        return {'masters': ''}


class profile_mixin(mixins.TempDirMixin, base_test):

    addon_kls = addons.ProfileAddon

    def setUp(self):
        mixins.TempDirMixin.setUp(self)
        base_test.setUp(self)

    def process_check(self, profile_base, *args, **kwds):
        options = base_test.process_check(self, *args, **kwds)
        options.search_repo = Options()
        if profile_base is None:
            repo = QuietRepoConfig(self.dir)
        else:
            repo = QuietRepoConfig(profile_base, profiles_base='.')
        options.target_repo = Options(config=repo)
        return options


class TestProfileAddon(profile_mixin):

    def mk_profiles(self, profiles, base='default', arches=None):
        loc = pjoin(self.dir, base)
        os.mkdir(loc)
        for profile in profiles:
            self.assertTrue(ensure_dirs(pjoin(loc, profile)),
                            msg="failed creating profile %r" % profile)
        if arches is None:
            arches = set(val[0] for val in profiles.itervalues())
        write_file(pjoin(loc, 'arch.list'), 'w', "\n".join(arches))
        write_file(pjoin(loc, 'repo_name'), 'w', 'testing')
        with open(pjoin(loc, 'profiles.desc'), 'w') as fd:
            for profile, vals in profiles.iteritems():
                l = len(vals)
                if l == 1 or not vals[1]:
                    fd.write("%s\t%s\tstable\n" % (vals[0], profile))
                else:
                    fd.write("%s\t%s\t%s\n" % (vals[0], profile, vals[1]))
                if l == 3 and vals[2]:
                    with open(pjoin(loc, profile, 'deprecated'), 'w') as f:
                        f.write("foon\n#dar\n")
                with open(pjoin(loc, profile, 'make.defaults'), 'w') as f:
                    f.write("ARCH=%s\n" % vals[0])
                with open(pjoin(loc, profile, 'eapi'), 'w') as f:
                    f.write('5')

    def assertProfiles(self, check, key, *profile_names):
        self.assertEqual(
            sorted(x.name for y in check.profile_evaluate_dict[key] for x in y),
            sorted(profile_names))

    def test_defaults(self):
        self.mk_profiles({
            "profile1": ["x86"],
            "profile1/2": ["x86"]},
            base='profiles')
        os.mkdir(pjoin(self.dir, 'metadata'))
        # write masters= to suppress logging complaints.
        write_file(pjoin(self.dir, 'metadata', 'layout.conf'), 'w', 'masters=')
        options = self.process_check(None, [],
            profiles_enabled=[], profiles_disabled=[],
            profile_ignore_deprecated=False, profiles_desc_enabled=True,
            profile_ignore_dev=False, profile_ignore_exp=False)
        # override the default
        check = self.addon_kls(options)
        self.assertEqual(sorted(check.official_arches), ['x86'])
        self.assertEqual(sorted(check.desired_arches), ['x86'])
        self.assertEqual(sorted(check.profile_evaluate_dict), ['x86', '~x86'])
        self.assertProfiles(check, 'x86', 'profile1', 'profile1/2')

    def test_profile_base(self):
        self.mk_profiles({
            "default-linux": ["x86", "dev"],
            "default-linux/x86": ["x86"]},
            base='foo')
        options = self.process_check(pjoin(self.dir, 'foo'), [])
        check = self.addon_kls(options)
        self.assertProfiles(check, 'x86', 'default-linux', 'default-linux/x86')

    def test_disable_dev(self):
        self.mk_profiles({
            "default-linux": ["x86", "dev"],
            "default-linux/x86": ["x86"]},
            base='foo')
        options = self.process_check(pjoin(self.dir, 'foo'), ['--profile-disable-dev'],
            profile_ignore_dev=True)
        check = self.addon_kls(options)
        self.assertProfiles(check, 'x86', 'default-linux/x86')

    def test_disable_deprecated(self):
        self.mk_profiles({
            "default-linux": ["x86", False, True],
            "default-linux/x86": ["x86"]},
            base='foo')
        options = self.process_check(pjoin(self.dir, 'foo'), ['--profile-disable-deprecated'],
            profile_ignore_deprecated=True)
        check = self.addon_kls(options)
        self.assertProfiles(check, 'x86', 'default-linux/x86')

    def test_disable_exp(self):
        self.mk_profiles({
            "default-linux": ["x86", "exp"],
            "default-linux/x86": ["x86"]},
            base='foo')
        options = self.process_check(pjoin(self.dir, 'foo'), ['--profile-disable-exp'],
            profile_ignore_exp=True)
        check = self.addon_kls(options)
        self.assertProfiles(check, 'x86', 'default-linux/x86')

    def test_disable_profiles_desc(self):
        self.mk_profiles({
            "default-linux": ["x86"],
            "default-linux/x86": ["x86"]},
            base='foo')
        options = self.process_check(pjoin(self.dir, 'foo'), ['--profile-disable-profiles-desc'])
        check = self.addon_kls(options)
        self.assertProfiles(check, 'x86')

    def test_profile_enable(self):
        self.mk_profiles({
            "default-linux": ["x86"],
            "default-linux/x86": ["x86"]},
            base='foo')
        options = self.process_check(pjoin(self.dir, 'foo'), ['--profile-disable-profiles-desc',
            '--enable-profiles', 'default-linux/x86'])
        check = self.addon_kls(options)
        self.assertProfiles(check, 'x86', 'default-linux/x86')

    def test_profile_disable(self):
        self.mk_profiles({
            "default-linux": ["x86"],
            "default-linux/x86": ["x86"]},
            base='foo')
        options = self.process_check(pjoin(self.dir, 'foo'), ['--disable-profiles', 'default-linux/x86'])
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
            path = pjoin(self.dir, 'foo', str(counter.next()))
            shutil.copytree(pjoin(self.dir, 'foo'), path, symlinks=True)
            return self.process_check(path, list(args))

        options = run_check()
        check = self.addon_kls(options)
        # assert they're collapsed properly.
        self.assertProfiles(check, 'x86', 'default-linux', 'default-linux/x86')
        self.assertEqual(len(check.profile_evaluate_dict['x86']), 1)
        self.assertEqual(len(check.profile_evaluate_dict['x86'][0]), 2)
        self.assertProfiles(check, 'ppc', 'default-linux/ppc')

        l = check.identify_profiles(FakePkg("d-b/ab-1", data={'KEYWORDS': 'x86'}))
        self.assertEqual(len(l), 1, msg="checking for profile collapsing: %r" % l)
        self.assertEqual(len(l[0]), 2, msg="checking for proper # of profiles: %r" % l[0])
        self.assertEqual(sorted(x.name for x in l[0]),
                         sorted(['default-linux', 'default-linux/x86']))

        # check keyword collapsing
        l = check.identify_profiles(FakePkg("d-b/ab-2", data={'KEYWORDS': 'ppc'}))
        self.assertEqual(len(l), 1, msg="checking for profile collapsing: %r" % l)
        self.assertEqual(len(l[0]), 1, msg="checking for proper # of profiles: " "%r" % l[0])
        self.assertEqual(l[0][0].name, 'default-linux/ppc')

        l = check.identify_profiles(FakePkg("d-b/ab-2", data={'KEYWORDS': 'foon'}))
        self.assertEqual(len(l), 0, msg="checking for profile collapsing: %r" % l)

        # test collapsing reusing existing profile layout
        with open(pjoin(self.dir, 'foo', 'default-linux', 'use.mask'), 'w') as f:
            f.write("lib")
        options = run_check()
        check = self.addon_kls(options)
        self.assertProfiles(check, 'x86', 'default-linux', 'default-linux/x86')
        self.assertEqual(len(check.profile_evaluate_dict['x86']), 2)

        with open(pjoin(self.dir, 'foo', 'default-linux', 'x86', 'use.mask'), 'w') as f:
            f.write("lib")
        options = run_check()
        check = self.addon_kls(options)
        self.assertProfiles(check, 'x86', 'default-linux', 'default-linux/x86')
        self.assertEqual(len(check.profile_evaluate_dict['x86']), 1)

        # test collapsing reusing existing profile layout
        with open(pjoin(self.dir, 'foo', 'default-linux', 'use.force'), 'w') as f:
            f.write("foo")
        options = run_check()
        check = self.addon_kls(options)
        self.assertProfiles(check, 'x86', 'default-linux', 'default-linux/x86')
        self.assertEqual(len(check.profile_evaluate_dict['x86']), 2)

        with open(pjoin(self.dir, 'foo', 'default-linux', 'x86', 'use.force'), 'w') as f:
            f.write("foo")
        options = run_check()
        check = self.addon_kls(options)
        self.assertProfiles(check, 'x86', 'default-linux', 'default-linux/x86')
        self.assertEqual(len(check.profile_evaluate_dict['x86']), 1)


class TestEvaluateDepSetAddon(profile_mixin):

    addon_kls = addons.EvaluateDepSetAddon
    orig_addon_kls = addon_kls

    def setUp(self):
        profile_mixin.setUp(self)
        with open(pjoin(self.dir, "arch.list"), "w") as f:
            f.write("\n".join(addons.ArchesAddon.default_arches))
        self.addon_kls = self.orig_addon_kls

    process_check = base_test.process_check

    def get_check(self, *profiles):
        # basically carefully tweak profileaddon to get ourself an instance
        # since evaluate relies on it.
        self.addon_kls = addons.ProfileAddon
        profile_options = profile_mixin.process_check(
            self, self.dir, ['--profile-disable-profiles-desc'] +
            ['--enable-profiles=%s' % ','.join(x.name for x in profiles)])
        self.addon_kls = self.orig_addon_kls
        profiles = dict((x.name, x) for x in profiles)
        profiles_obj = Options(create_profile=lambda x: profiles[x])
        # XXX: Cheat.
        object.__setattr__(profile_options.target_repo.config, '_profiles',
                           profiles_obj)
        profile_check = addons.ProfileAddon(profile_options)

        # now we're good to go.
        return self.addon_kls(profile_options, profile_check)

    def test_it(self):
        check = self.get_check(
            FakeProfile(stable_masked_use={"dev-util/diffball": ['foo']},
                arch='x86', name='1'),
            FakeProfile(stable_forced_use={"=dev-util/diffball-0.1": ['bar', 'foo']},
                arch='x86', name='2'),
            FakeProfile(stable_forced_use={"dev-util/diffball": ['bar', 'foo']},
                arch='ppc', name='3')
            )
        def get_rets(ver, attr, KEYWORDS="x86", **data):
            data["KEYWORDS"] = KEYWORDS
            pkg = FakePkg("dev-util/diffball-%s" % ver, data=data)
            return check.collapse_evaluate_depset(pkg, attr,
                getattr(pkg, attr))

        # few notes... for ensuring proper profiles came through, use
        # sorted(x.name for x in blah); reasoning is that it will catch
        # if duplicates come through, *and* ensure proper profile collapsing

        # shouldn't return anything due to no profiles matching the keywords.
        self.assertEqual(get_rets("0.0.1", "depends", KEYWORDS="foon"), [])
        l = get_rets("0.0.2", "depends")
        self.assertEqual(len(l), 1, msg="must collapse all profiles down "
            "to one run: got %r" % l)
        self.assertEqual(sorted(x.name for x in l[0][1]), ['1', '2'],
            msg="must have just two profiles: got %r" % l)
        self.assertEqual(l[0][1][0].key, 'x86')
        self.assertEqual(l[0][1][1].key, 'x86')

        l = get_rets("0.1", "rdepends",
            RDEPEND="x? ( dev-util/confcache ) foo? ( dev-util/foo ) "
            "bar? ( dev-util/bar ) !bar? ( dev-util/nobar ) x11-libs/xserver")

        self.assertEqual(len(l), 2, msg="must collapse all profiles down "
            "to 2 runs: got %r" % l)
        profiles = sorted(x[1][0].name for x in l)
        self.assertEqual(profiles[0], '1',
            msg="got %r, expected single profile" % profiles[0])
        self.assertEqual(profiles[1], '2',
            msg="got %r, expected single profile" % profiles[1])

        # ordering is potentially random; thus pull out which depset result is
        # which based upon profile
        l1 = [x for x in l if x[1][0].name == '1'][0]
        l2 = [x for x in l if x[1][0].name == '2'][0]

        self.assertEqual(set(str(l1[0]).split()),
            set(['dev-util/confcache', 'dev-util/bar', 'dev-util/nobar',
                'x11-libs/xserver']))

        self.assertEqual(set(str(l2[0]).split()),
            set(['dev-util/confcache', 'dev-util/foo', 'dev-util/bar',
                'x11-libs/xserver']))

        # test feed wiping, using an empty depset; if it didn't clear, then
        # results from a pkg/attr tuple from above would come through rather
        # then an empty.
        check.feed(None, None)
        l = get_rets("0.1", "rdepends")
        self.assertEqual(len(l), 1,
            msg="feed didn't clear the cache- should be len 1: %r" % l)

        check.feed(None, None)

        # ensure it handles arch right.
        l = get_rets("0", "depends", KEYWORDS="ppc x86")
        self.assertEqual(len(l), 1, msg="should be len 1, got %r" % l)
        self.assertEqual(sorted(x.name for x in l[0][1]), ["1", "2", "3"],
            msg="should have 3 profiles of 1-3, got %r" % l[0][1])

        # ensure it's caching profile collapsing, iow, keywords for same ver
        # that's partially cached (single attr at least) should *not* change
        # things.

        l = get_rets("0", "depends", KEYWORDS="ppc")
        self.assertEqual(sorted(x.name for x in l[0][1]), ['1', '2', '3'],
            msg="should have 3 profiles, got %r\nthis indicates it's "
            "re-identifying profiles every invocation, which is unwarranted "
            % l[0][1])

        l = get_rets("1", "depends", KEYWORDS="ppc x86",
            DEPEND="ppc? ( dev-util/ppc ) !ppc? ( dev-util/x86 )")
        self.assertEqual(len(l), 2, msg="should be len 2, got %r" % l)

        # same issue, figure out what is what
        l1 = [x[1] for x in l if str(x[0]).strip() == "dev-util/ppc"][0]
        l2 = [x[1] for x in l if str(x[0]).strip() == "dev-util/x86"][0]

        self.assertEqual(sorted(x.name for x in l1), ["3"])
        self.assertEqual(sorted(x.name for x in l2), ["1", "2"])


class TestLicenseAddon(mixins.TempDirMixin, base_test):

    addon_kls = addons.LicenseAddon

    def test_defaults(self):
        r1 = pjoin(self.dir, "repo1")
        r2 = pjoin(self.dir, "repo2")
        os.mkdir(r1)
        os.mkdir(pjoin(r1, "licenses"))
        os.mkdir(r2)

        self.assertRaises(optparse.OptionValueError, self.process_check, [],
            preset_values={'repo_bases': [r2]})

        self.process_check([], preset_values={'repo_bases': [r1, r2]},
            license_dirs=[pjoin(r1, 'licenses')])

    def test_it(self):
        opts = self.process_check(['--license-dir', self.dir],
            license_dirs=[self.dir])
        open(pjoin(self.dir, 'foo'), 'w').close()
        open(pjoin(self.dir, 'foo2'), 'w').close()
        self.assertRaises(optparse.OptionValueError, self.process_check,
            ['--license-dir', pjoin(self.dir, 'foo')])
        addon = self.addon_kls(opts)
        self.assertEqual(frozenset(['foo', 'foo2']),
            addon.licenses)


class TestUseAddon(mixins.TempDirMixin, base_test):

    addon_kls = addons.UseAddon

    def test_it(self):
        pass
    test_it.skip = "todo"
