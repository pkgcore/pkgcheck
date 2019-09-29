import pytest

from pkgcheck import base, checks, pipeline, sources


dummies = list(f'dummy-{i}' for i in range(0, 10))


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


class DummySource(sources.GenericSource):

    """Dummy source object just "producing" itself.

    You should use the instances in the L{sources} tuple instead of
    creating your own.
    """

    def __init__(self, dummy, scope=base.package_scope):
        self.feed_type = dummy
        self.scope = scope

    def __repr__(self):
        return f'{self.__class__.__name__}({self.feed_type})'


class DummySink(checks.Check):

    """Dummy sink object just yielding every fed to it with itself appended.

    You should use the instances in the L{sinks} tuple instead of
    creating your own.
    """

    source = DummySource

    def __init__(self, dummy, scope=base.package_scope):
        self.feed_type = dummy
        self.scope = scope

    def __repr__(self):
        return f'{self.__class__.__name__}({self.feed_type})'


sources = tuple(DummySource(dummy) for dummy in dummies)
sinks = tuple(DummySink(dummy) for dummy in dummies)


class TestPlug(object):

    def assertPipes(self, sinks, sources, *expected_pipes, **kw):
        """Check if the plug function yields the expected pipelines.

        The first three arguments are passed through to plug.
        Further arguments are the pipes that should be returned.
        They are interpreted as a set (since the return order from plug
        is unspecified).
        """
        # Writing this the "normal" way interprets the first optional
        # positional arg incorrectly.
        expected_pipes = set(expected_pipes)
        if kw:
            raise TypeError(f'unsupported kwargs {list(kw.keys())!r}')
        try:
            pipes = pipeline.plug(sinks, sources)
        except KeyboardInterrupt:
            raise
        actual_pipes = set(pipes)
        good = expected_pipes & actual_pipes
        expected_pipes -= good
        actual_pipes -= good
        if expected_pipes or actual_pipes:
            # Failure. Build message.
            message = ['', '']
            message.extend(['', 'Expected:'])
            for pipe in expected_pipes:
                message.append(str(pipe))
            message.extend(['', 'Got:'])
            for pipe in actual_pipes:
                message.append(str(pipe))
            pytest.fail('\n'.join(message))

    def test_simple(self):
        self.assertPipes(
            [sinks[0]],
            {DummySource: sources[0]},
            (sources[0], pipeline.CheckRunner([sinks[0]])))
        self.assertPipes(
            [sinks[0]],
            {DummySource: sources[0]},
            (sources[0], pipeline.CheckRunner([sinks[0]])))
