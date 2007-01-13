# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: GPL2

import os, sys, optparse
from pkgcore.util.osutils import pjoin, ensure_dirs
from pkgcore.test import TestCase, mixins
from pkgcore_checks import addons, base
from pkgcore_checks.test.misc import FakePkg


class exit_exception(Exception):
    def __init__(self, *args):
        self.args = args

class parser(optparse.OptionParser):

    def exit(self, *args):
        raise exit_exception(*args)

class base_test(TestCase):

    addon_kls = None
    
    def process_check(self, args, silence=False, preset_vals={}, **settings):
        p = parser()
        self.addon_kls.mangle_option_parser(p)
        options, ret_args = p.parse_args(args)
        self.assertFalse(ret_args, msg="%r args were left after processing %r" % 
            (ret_args, args))
        orig_out, orig_err = None, None
        for attr, val in preset_vals.iteritems():
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
                    sys.stdout = orig_out
                if orig_err:
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
            self.process_check(['--reset-caching-per', val],
                query_caching_freq=ret, silence=True)

    def test_default(self):
        self.process_check([], silence=True,
            query_caching_freq=self.default_feed)
    
    def test_feed(self):
        options = self.process_check([], silence=True)
        check = self.addon_kls(options)
        check.start()
        self.assertEqual(check.feed_type, self.default_feed)
        check.query_cache["boobies"] = "hooray for"
        check.feed(None, None)
        self.assertFalse(check.query_cache)


class TestProfileAddon(mixins.TempDirMixin, base_test):

    addon_kls = addons.ProfileAddon
    
    def mk_profiles(self, profiles, base='default', arches=None):
        loc = pjoin(self.dir, base)
        os.mkdir(loc)
        for profile in profiles:
            self.assertTrue(ensure_dirs(pjoin(loc, profile)),
                msg="failed creating profile %r" % profile)
        if arches is None:
            arches = set(val[0] for val in profiles.itervalues())
        open(pjoin(loc, 'arch.list'), 'w').write("\n".join(arches))
        fd = open(pjoin(loc, 'profiles.desc'), 'w')
        for profile, vals in profiles.iteritems():
            l = len(vals)
            if l == 1 or not vals[1]:
                fd.write("%s\t%s\tstable\n" % (vals[0], profile))
            else:
                fd.write("%s\t%s\tdev\n" % (vals[0], profile))
            if l == 3 and vals[2]:
                open(pjoin(loc, profile, 'deprecated'), 'w').write("foon\n#dar\n")
            open(pjoin(loc, profile, 'make.defaults'), 'w').write(
                "ARCH=%s\n" % vals[0])
        fd.close()

    def assertProfiles(self, check, key, *profile_names):
        self.assertEqual(
            sorted(x.name for y in check.profile_evaluate_dict[key] for x in y),
            sorted(profile_names))

    def process_check(self, *args, **kwds):
        options = base_test.process_check(self, *args, **kwds)
        class c:pass
        options.search_repo = c()
        return options
    
    def test_default(self):
        self.mk_profiles({"profile1":["x86"], "profile1/2":["x86"]}, base='profiles')
        class fake_repo:
            base = self.dir
        options = self.process_check([],
            preset_vals={"src_repo":fake_repo()},
            profiles_enabled=[], profiles_disabled=[],
            profile_ignore_deprecated=False, profiles_desc_enabled=True,
            profile_ignore_dev=False)
        # override the default
        options.search_repo = options.src_repo
        check = self.addon_kls(options)
        self.assertEqual(sorted(check.official_arches), ['x86'])
        self.assertEqual(sorted(check.desired_arches), ['x86'])
        self.assertEqual(sorted(check.profile_evaluate_dict), ['x86', '~x86'])
        self.assertProfiles(check, 'x86', 'profile1', 'profile1/2')
    
    def test_profile_base(self):
        self.mk_profiles({"default-linux":["x86", True],
            "default-linux/x86":["x86"]}, base='foo')
        options = self.process_check(['--profile-base', pjoin(self.dir, 'foo')])
        check = self.addon_kls(options)
        self.assertProfiles(check, 'x86', 'default-linux', 'default-linux/x86')

    def test_disable_dev(self):
        self.mk_profiles({"default-linux":["x86", True],
            "default-linux/x86":["x86"]}, base='foo')
        options = self.process_check(['--profile-base', pjoin(self.dir, 'foo'),
            '--profile-disable-dev'], 
            profile_ignore_dev=True)
        check = self.addon_kls(options)
        self.assertProfiles(check, 'x86', 'default-linux/x86')

    def test_disable_deprecated(self):
        self.mk_profiles({"default-linux":["x86", False, True],
            "default-linux/x86":["x86"]}, base='foo')
        options = self.process_check(['--profile-base', pjoin(self.dir, 'foo'),
            '--profile-disable-deprecated'],
            profile_ignore_deprecated=True)
        check = self.addon_kls(options)
        self.assertProfiles(check, 'x86', 'default-linux/x86')

    def test_disable_profiles_desc(self):
        self.mk_profiles({"default-linux":["x86"],
            "default-linux/x86":["x86"]}, base='foo')
        options = self.process_check(['--profile-base', pjoin(self.dir, 'foo'),
            '--profile-disable-profiles-desc'])
        check = self.addon_kls(options)
        self.assertProfiles(check, 'x86')

    def test_profile_enable(self):
        self.mk_profiles({"default-linux":["x86"],
            "default-linux/x86":["x86"]}, base='foo')
        options = self.process_check(['--profile-base', pjoin(self.dir, 'foo'),
            '--profile-disable-profiles-desc',
            '--profile-enable', 'default-linux/x86'])
        check = self.addon_kls(options)
        self.assertProfiles(check, 'x86', 'default-linux/x86')

    def test_profile_disable(self):
        self.mk_profiles({"default-linux":["x86"],
            "default-linux/x86":["x86"]}, base='foo')
        options = self.process_check(['--profile-base', pjoin(self.dir, 'foo'),
            '--profile-disable', 'default-linux/x86'])
        check = self.addon_kls(options)
        self.assertProfiles(check, 'x86', 'default-linux')

    def test_identify_profiles(self):
        self.mk_profiles({'default-linux':['x86'],
            'default-linux/x86':["x86"], 'default-linux/ppc':['ppc']},
            base='foo')
        options = self.process_check(['--profile-base', pjoin(self.dir, 'foo')])
        check = self.addon_kls(options)
        self.assertProfiles(check, 'x86', 'default-linux', 'default-linux/x86')
        self.assertProfiles(check, 'ppc', 'default-linux/ppc')

        l = check.identify_profiles(FakePkg("d-b/ab-1", data={'KEYWORDS':'x86'}))
        self.assertEqual(len(l), 1, msg="checking for profile collapsing: %r" %
            l)
        self.assertEqual(len(l[0]), 2, msg="checking for proper # of profiles: "
            "%r" % l[0])
        self.assertEqual(sorted(x.name for x in l[0]), 
            sorted(['default-linux', 'default-linux/x86']))
        
        l = check.identify_profiles(FakePkg("d-b/ab-2", data={'KEYWORDS':'ppc'}))
        self.assertEqual(len(l), 1, msg="checking for profile collapsing: %r" %
            l)
        self.assertEqual(len(l[0]), 1, msg="checking for proper # of profiles: "
            "%r" % l[0])
        self.assertEqual(l[0][0].name, 'default-linux/ppc')

        l = check.identify_profiles(FakePkg("d-b/ab-2", data={'KEYWORDS':'foon'}))
        self.assertEqual(len(l), 0, msg="checking for profile collapsing: %r" %
            l)
        
