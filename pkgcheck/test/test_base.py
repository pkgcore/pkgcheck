# Copyright: 2006 Marien Zwart <marienz@gentoo.org>
# License: BSD/GPL2

from pkgcore.test import TestCase

from pkgcheck import base


dummies = list('dummy-%s' % (i,) for i in xrange(0, 10))


class UtilitiesTest(TestCase):

    def test_convert_check_filter(self):
        self.assertTrue(base.convert_check_filter('foo')('a.foO.b'))
        self.assertFalse(base.convert_check_filter('foo')('a.foObaR'))
        self.assertFalse(base.convert_check_filter('foo.*')('a.fOoBar'))
        self.assertTrue(base.convert_check_filter('foo.*')('fOoBar'))
        self.assertTrue(base.convert_check_filter('foo.bar')('foo.bar.baz'))
        self.assertTrue(base.convert_check_filter('bar.baz')('foo.bar.baz'))
        self.assertFalse(base.convert_check_filter('baz.spork')('foo.bar.baz'))
        self.assertFalse(base.convert_check_filter('bar.foo')('foo.bar.baz'))


class DummySource(object):

    """Dummy source object just "producing" itself.

    You should use the instances in the L{sources} tuple instead of
    creating your own.
    """

    cost = 10

    def __init__(self, dummy, scope=base.package_scope):
        self.feed_type = dummy
        self.scope = scope

    def __repr__(self):
        return '%s(%s)' % (self.__class__.__name__, self.feed_type)


class DummySink(base.Template):

    """Dummy sink object just yielding every fed to it with itself appended.

    You should use the instances in the L{sinks} tuple instead of
    creating your own.
    """

    def __init__(self, dummy, scope=base.package_scope):
        self.feed_type = dummy
        self.scope = scope

    def __repr__(self):
        return '%s(%s)' % (self.__class__.__name__, self.feed_type)


def trans(source, dest, cost=10, scope=base.package_scope):
    """Builds dummy transform classes.

    The classes can be sensibly compared to each other, so comparing
    the return value from a manual call to this function to classe in
    the predefined L{trans_up}, L{trans_down} and L{trans_everything}
    sequences works.
    """

    class DummyTransform(base.Transform):

        """Dummy transform object."""

        def __repr__(self):
            return ('%(class)s(%(source)s, %(dest)s, cost=%(cost)s, '
                    'scope=%(scope)s, child=%(child)s)') % {
                'class': self.__class__.__name__,
                'source': self.source,
                'dest': self.dest,
                'cost': self.cost,
                'scope': self.scope,
                'child': self.child,
                }

        def __eq__(self, other):
            return (self.source == other.source and
                    self.dest == other.dest and
                    self.scope == other.scope and
                    self.cost == other.cost and
                    self.child == other.child)

        def __ne__(self, other):
            return not self == other

        def __hash__(self):
            return hash((self.source, self.dest, self.scope, self.cost))
    DummyTransform.source = dummies[source]
    DummyTransform.dest = dummies[dest]
    DummyTransform.cost = cost
    DummyTransform.scope = scope
    return DummyTransform


sources = tuple(DummySource(dummy) for dummy in dummies)
trans_everything = tuple(trans(source, target)
                         for source in xrange(len(dummies))
                         for target in xrange(len(dummies)))
trans_up = tuple(trans(i, i + 1) for i in xrange(len(dummies) - 1))
trans_down = tuple(trans(i + 1, i) for i in xrange(len(dummies) - 1))
sinks = tuple(DummySink(dummy) for dummy in dummies)


class PlugTest(TestCase):

    def assertPipes(self, sinks, transforms, sources, *expected_pipes, **kw):
        """Check if the plug function yields the expected pipelines.

        The first three arguments are passed through to plug.
        Further arguments are the pipes that should be returned.
        They are interpreted as a set (since the return order from plug
        is unspecified).
        bad_sinks is accepted as keyword args, defaulting to the empty list.
        """
        # Writing this the "normal" way interprets the first optional
        # positional arg incorrectly.
        bad_sinks = kw.pop('bad_sinks', [])
        expected_pipes = set(expected_pipes)
        if kw:
            raise TypeError('unsupported kwargs %r' % (kw.keys(),))
        try:
            actual_bad_sinks, pipes = base.plug(sinks, transforms, sources)
        except KeyboardInterrupt:
            raise
        except Exception:
            print
            print 'Test erroring, rerunning in debug mode'
            # Rerun in debug mode.
            def _debug(message, *args):
                print message % args
            base.plug(sinks, transforms, sources, _debug)
            # Should not reach this since base.plug should raise again.
            raise
        actual_pipes = set(pipes)
        good = expected_pipes & actual_pipes
        expected_pipes -= good
        actual_pipes -= good
        if expected_pipes or actual_pipes:
            # Failure. Build message.
            message = ['', '']
            def _debug(format, *args):
                message.append(format % args)
            base.plug(sinks, transforms, sources, _debug)
            message.extend(['', 'Expected:'])
            for pipe in expected_pipes:
                message.append(str(pipe))
            message.extend(['', 'Got:'])
            for pipe in actual_pipes:
                message.append(str(pipe))
            self.fail('\n'.join(message))
        self.assertEqual(bad_sinks, actual_bad_sinks)

    def test_plug(self):
        self.assertPipes(
            [sinks[2]],
            trans_everything,
            [sources[0]],
            (sources[0], base.CheckRunner([
                trans(0, 2)(base.CheckRunner([sinks[2]]))])))
        self.assertPipes(
            [sinks[2]],
            trans_up,
            [sources[0]],
            (sources[0], base.CheckRunner([
                trans(0, 1)(base.CheckRunner([
                    trans(1, 2)(base.CheckRunner([sinks[2]])),
                    ]))])))

    def test_no_transform(self):
        self.assertPipes(
            [sinks[0]],
            trans_everything,
            [sources[0]],
            (sources[0], base.CheckRunner([sinks[0]])))
        self.assertPipes(
            [sinks[0]],
            [],
            [sources[0]],
            (sources[0], base.CheckRunner([sinks[0]])))

    def test_too_many_sources(self):
        self.assertPipes(
            [sinks[3]],
            trans_everything,
            sources,
            (sources[3], base.CheckRunner([sinks[3]])))
        self.assertPipes(
            [sinks[2], sinks[4]],
            [trans(1, 2), trans(3, 4), trans(4, 5)],
            [sources[1], sources[3]],
            (sources[1], base.CheckRunner([trans(1, 2)(base.CheckRunner([
                sinks[2]]))])),
            (sources[3], base.CheckRunner([trans(3, 4)(base.CheckRunner([
                sinks[4]]))])))

    def test_grow(self):
        self.assertPipes(
            [sinks[1], sinks[0]],
            trans_up,
            [sources[0]],
            (sources[0], base.CheckRunner([
                sinks[0],
                trans(0, 1)(base.CheckRunner([sinks[1]]))])))
        self.assertPipes(
            [sinks[1], sinks[0]],
            trans_everything,
            [sources[0]],
            (sources[0], base.CheckRunner([
                sinks[0],
                trans(0, 1)(base.CheckRunner([sinks[1]]))])))
        self.assertPipes(
            [sinks[2], sinks[0]],
            trans_up,
            [sources[0]],
            (sources[0], base.CheckRunner([
                sinks[0],
                trans(0, 1)(base.CheckRunner([
                    trans(1, 2)(base.CheckRunner([sinks[2]])),
                    ]))])))
        self.assertPipes(
            [sinks[2], sinks[1]],
            trans_up,
            [sources[0]],
            (sources[0], base.CheckRunner([trans(0, 1)(base.CheckRunner([
                sinks[1],
                trans(1, 2)(base.CheckRunner([sinks[2]])),
                ]))])))

    def test_forks(self):
        self.assertPipes(
            [sinks[1], sinks[2], sinks[3]],
            [trans(1, 2), trans(1, 3)],
            [sources[1]],
            (sources[1], base.CheckRunner([
                sinks[1],
                trans(1, 2)(base.CheckRunner([sinks[2]])),
                trans(1, 3)(base.CheckRunner([sinks[3]])),
                ])))
        self.assertPipes(
            [sinks[1], sinks[2], sinks[3]],
            [trans(0, 1), trans(1, 2), trans(1, 3)],
            [sources[0]],
            (sources[0], base.CheckRunner([
                trans(0, 1)(base.CheckRunner([
                    sinks[1],
                    trans(1, 2)(base.CheckRunner([sinks[2]])),
                    trans(1, 3)(base.CheckRunner([sinks[3]])),
                    ]))])))
        self.assertPipes(
            [sinks[0], sinks[1], sinks[2]],
            (trans(1, 2),) + trans_down,
            [sources[1]],
            (sources[1], base.CheckRunner([
                sinks[1],
                trans(1, 2)(base.CheckRunner([sinks[2]])),
                trans(1, 0)(base.CheckRunner([sinks[0]])),
                ])))

    def test_scope(self):
        sink1 = DummySink(dummies[1], 1)
        sink2 = DummySink(dummies[2], 2)
        sink3 = DummySink(dummies[3], 3)
        source = DummySource(dummies[1], 3)
        self.assertPipes(
            [sink1, sink2, sink3],
            [trans(1, 2), trans(2, 3)],
            [source],
            (source, base.CheckRunner([
                sink1,
                trans(1, 2)(base.CheckRunner([
                    sink2,
                    trans(2, 3)(base.CheckRunner([sink3])),
                    ]))])))

    def test_scope_affects_transform_cost(self):
        trans_fast = trans(1, 2, scope=base.repository_scope, cost=1)
        trans_slow = trans(1, 2, scope=base.package_scope, cost=10)
        self.assertPipes(
            [sinks[2]],
            [trans_slow, trans_fast],
            [sources[1]],
            (sources[1], base.CheckRunner([
                trans_slow(base.CheckRunner([sinks[2]]))])))
        source = DummySource(dummies[1], scope=base.repository_scope)
        self.assertPipes(
            [sinks[2]],
            [trans_slow, trans_fast],
            [source],
            (source, base.CheckRunner([
                trans_fast(base.CheckRunner([sinks[2]]))])))
