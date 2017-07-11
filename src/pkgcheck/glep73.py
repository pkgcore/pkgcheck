from pkgcore.restrictions.boolean import (OrRestriction, AndRestriction,
        JustOneRestriction, AtMostOneOfRestriction)
from pkgcore.restrictions.packages import Conditional
from pkgcore.restrictions.values import ContainmentMatch

from pkgcheck import base


class GLEP73Syntax(base.Warning):
    """REQUIRED_USE constraints whose syntax violates the restrictions
    set in GLEP 73. They are complex or otherwise potentially surprising
    and can be easily replaced by more readable constructs."""

    __slots__ = ("category", "package", "version", "required_use", "issue")
    threshold = base.versioned_feed

    def __init__(self, pkg, required_use, issue):
        super(GLEP73Syntax, self).__init__()
        self._store_cpv(pkg)
        self.required_use = required_use
        self.issue = issue

    @property
    def short_desc(self):
        return 'REQUIRED_USE syntax violates GLEP 73: %s (in %s)' % (
                self.issue, self.required_use)


glep73_known_results = (GLEP73Syntax,)


def group_name(c):
    """Return a user-friendly name of the specific restriction."""
    if isinstance(c, OrRestriction):
        return 'any-of'
    elif isinstance(c, JustOneRestriction):
        return 'exactly-one-of'
    elif isinstance(c, AtMostOneOfRestriction):
        return 'at-most-one-of'
    elif isinstance(c, AndRestriction):
        return 'all-of'
    elif isinstance(c, Conditional):
        return 'USE-conditional'
    else:
        raise AssertionError('Unexpected type in group_name(): %s' % (c,))


def glep73_validate_syntax(requse, reporter, pkg):
    """Validate whether the REQUIRED_USE constraint matches the syntax
    restrictions in GLEP 73, i.e. does not contain all-of groups
    and ||/??/^^ groups are flat and non-empty."""
    for c in requse:
        if isinstance(c, AndRestriction):
            # TODO: pkgcore normalizes nested meaningless and-of groups
            # figure out how to detect them
            reporter.add_report(GLEP73Syntax(
                pkg, pkg.required_use, 'all-of groups are forbidden'))
            return False
        elif (isinstance(c, OrRestriction) or
              isinstance(c, JustOneRestriction) or
              isinstance(c, AtMostOneOfRestriction)):
            # ||/^^/?? can contain only flat flags -- nesting is forbidden
            for f in c:
                if not isinstance(f, ContainmentMatch):
                    reporter.add_report(GLEP73Syntax(
                        pkg, pkg.required_use, 'nesting %s inside %s is forbidden'
                        % (group_name(f), group_name(c))))
                    return False
            if len(c) == 0:
                # pkgcheck already reports empty groups, so just return False
                return False
        elif isinstance(c, Conditional):
            # recurse on conditionals
            if not glep73_validate_syntax(c, reporter, pkg):
                return False
        elif isinstance(c, ContainmentMatch):
            # plain flag
            pass
        else:
            raise AssertionError('Unknown item in REQUIRED_USE: %s' % (c,))

    return True


class GLEP73Flag(object):
    """A trivial holder for flag name+value inside flat constraints.
    It replaces ContainmentMatch since the latter has instance caching
    which breaks identity comparison."""

    __slots__ = ('name', 'enabled')

    def __init__(self, name_or_restriction, negate=False):
        """Initialize either using a flag name (string) or
        a ContainmentMatch restriction. The value will be negated
        from the original if negate is True."""
        if isinstance(name_or_restriction, ContainmentMatch):
            assert(len(name_or_restriction.vals) == 1)
            self.name = next(iter(name_or_restriction.vals))
            # name_or_restriction.negate XOR negate
            self.enabled = (name_or_restriction.negate == negate)
        else:
            self.name = name_or_restriction
            self.enabled = not negate

    def __eq__(self, other):
        return self.name == other.name and self.enabled == other.enabled

    def __hash__(self):
        return hash((self.name, self.enabled))

    def __str__(self):
        return '%s%s' % ('' if self.enabled else '!', self.name)

    def __repr__(self):
        return 'GLEP73Flag("%s", negate=%s)' % (self.name, not self.enabled)


def glep73_flatten(requse):
    """Transform the REQUIRED_USE into flat constraints as described
    in GLEP 73."""
    def rec(restrictions, conditions):
        for c in restrictions:
            if isinstance(c, ContainmentMatch):
                # plain flag
                yield (conditions, GLEP73Flag(c))
            elif isinstance(c, Conditional):
                assert(c.attr == 'use')
                assert(isinstance(c.restriction, ContainmentMatch))
                # recurse on conditionals
                for x in rec(c, conditions+[GLEP73Flag(c.restriction)]):
                    yield x
            elif (isinstance(c, OrRestriction) or
                  isinstance(c, JustOneRestriction) or
                  isinstance(c, AtMostOneOfRestriction)):
                if not isinstance(c, AtMostOneOfRestriction):
                    # ^^ ( a b c ... ) -> || ( a b c ) ...
                    # || ( a b c ... ) -> [!b !c ...]? ( a )
                    yield (conditions + [GLEP73Flag(x, negate=True) for x in c.restrictions[1:]],
                           GLEP73Flag(c.restrictions[0]))
                if not isinstance(c, OrRestriction):
                    # ^^ ( a b c ... ) -> ... ?? ( a b c )
                    # ?? ( a b c ... ) -> a? ( !b !c ... ) b? ( !c ... ) ...
                    for i in range(0, len(c.restrictions)-1):
                        new_cond = conditions + [GLEP73Flag(x) for x in c.restrictions[i:i+1]]
                        for x in c.restrictions[i+1:]:
                            yield (new_cond, GLEP73Flag(x, negate=True))
            else:
                raise AssertionError('Unknown item in REQUIRED_USE: %s' % (c,))

    return list(rec(requse, []))
