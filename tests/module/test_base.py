from pkgcheck import base


class TestUtilities(object):

    def test_convert_check_filter(self):
        assert base.convert_check_filter('foo')('a.foO.b')
        assert not base.convert_check_filter('foo')('a.foObaR')
        assert not base.convert_check_filter('foo.*')('a.fOoBar')
        assert base.convert_check_filter('foo.*')('fOoBar')
        assert base.convert_check_filter('foo.bar')('foo.bar.baz')
        assert base.convert_check_filter('bar.baz')('foo.bar.baz')
        assert not base.convert_check_filter('baz.spork')('foo.bar.baz')
        assert not base.convert_check_filter('bar.foo')('foo.bar.baz')
