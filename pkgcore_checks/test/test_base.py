# Copyright: 2006 Marien Zwart <marienz@gentoo.org>
# License: GPL2


from pkgcore.test import TestCase

from pkgcore_checks import base


dummies = list('dummy-%s' % (i,) for i in xrange(0, 10))


class DummyTransform(object):

    def __init__(self, source, target, cost=10):
        self.transforms = [(source, target, cost)]

    def transform(self, chunks):
        for chunk in chunks:
            yield chunk
        yield self

    def __repr__(self):
        return '%s(%s, %s, %s)' % ((
                self.__class__.__name__,) + self.transforms[0])

    def __eq__(self, other):
        return (self.__class__ is other.__class__ and
                self.transforms == other.transforms)

    def __ne__(self, other):
        return not self == other

    def __hash__(self):
        return 0


class DummySource(object):

    cost = 10

    def __init__(self, dummy):
        self.feed_type = dummy

    def feed(self):
        yield self

    def __repr__(self):
        return '%s(%s)' % (self.__class__.__name__, self.feed_type)


class DummySink(object):

    def __init__(self, dummy):
        self.feed_type = dummy

    def feed(self, chunks, reporter):
        for chunk in chunks:
            yield chunk
        yield self

    def __repr__(self):
        return '%s(%s)' % (self.__class__.__name__, self.feed_type)


def trans(source, target, cost=10):
    return DummyTransform(dummies[source], dummies[target], cost)


sources = list(DummySource(dummy) for dummy in dummies)
trans_everything = list(DummyTransform(source, target)
                        for source in dummies for target in dummies)
trans_up = list(DummyTransform(dummies[i], dummies[i + 1])
                for i in xrange(len(dummies) - 1))
trans_down = list(DummyTransform(dummies[i + 1], dummies[i], 1)
                  for i in xrange(len(dummies) - 1))
sinks = list(DummySink(dummy) for dummy in dummies)


class PlugTest(TestCase):

    def assertPipes(self, sinks, transforms, sources, *expected_pipes):
        actual_pipes = base.plug(sinks, transforms, sources, None)
        try:
            self.assertEquals(len(expected_pipes), len(actual_pipes))
            for expected, actual in zip(expected_pipes, actual_pipes):
                expected_pipe = list(expected)
                actual_pipe = list(actual)
                self.assertEquals(
                    expected_pipe, actual_pipe,
                    '\nExpected:\n%s\nGot:\n%s\n' % (
                        '\n'.join(str(p) for p in expected_pipe),
                        '\n'.join(str(p) for p in actual_pipe)))
        except AssertionError:
            # Rerun in debug mode and reraise
            base.plug(sinks, transforms, sources, None, True)
            raise

    def test_plug(self):
        self.assertPipes(
            [sinks[2]],
            trans_everything,
            [sources[0]],
            [sources[0], trans(0, 2), sinks[2]])
        self.assertPipes(
            [sinks[2]],
            trans_up,
            [sources[0]],
            [sources[0], trans(0, 1), trans(1, 2), sinks[2]])

    def test_no_transform(self):
        self.assertPipes(
            [sinks[0]],
            trans_everything,
            [sources[0]],
            [sources[0], sinks[0]])
        self.assertPipes(
            [sinks[0]],
            [],
            [sources[0]],
            [sources[0], sinks[0]])

    def test_grow(self):
        self.assertPipes(
            [sinks[1], sinks[0]],
            trans_up,
            [sources[0]],
            [sources[0], sinks[0], trans(0, 1), sinks[1]])
        self.assertPipes(
            [sinks[2], sinks[1]],
            trans_up,
            [sources[0]],
            [sources[0], trans(0, 1), sinks[1], trans(1, 2), sinks[2]])
