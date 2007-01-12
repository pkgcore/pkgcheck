# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: GPL2

import optparse, sys
from pkgcore_checks import addons, base
from pkgcore.test import TestCase

class exit_exception(Exception):
    def __init__(self, *args):
        self.args = args

class parser(optparse.OptionParser):

    def exit(self, *args):
        raise exit_exception(*args)

class base_test(TestCase):

    addon_kls = None
    
    def process_check(self, args, silence=False, **settings):
        p = parser()
        self.addon_kls.mangle_option_parser(p)
        options, ret_args = p.parse_args(args)
        self.assertFalse(ret_args, msg="%r args were left after processing %r" % 
            (ret_args, args))
        orig_out, orig_err = None, None
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

