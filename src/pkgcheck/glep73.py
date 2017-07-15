from functools import partial

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


class GLEP73Immutability(base.Error):
    """REQUIRED_USE constraints that can request the user to enable
    (disable) a flag that is masked (forced). This is both a problem
    for the auto-enforcing and for regular users which can hit
    unsolvable requests."""

    __slots__ = ("category", "package", "version", "condition",
                 "enforcement", "profiles")
    threshold = base.versioned_feed

    def __init__(self, pkg, condition, enforcement, profiles):
        super(GLEP73Immutability, self).__init__()
        self._store_cpv(pkg)
        self.condition = condition
        self.enforcement = enforcement
        self.profiles = profiles

    @property
    def short_desc(self):
        return ('REQUIRED_USE violates immutability rules: ' +
                '[%s] requires [%s] while the opposite value is ' +
                'enforced by use.force/mask (in profiles: %s)') % (
                ' && '.join('%s' % x for x in self.condition),
                self.enforcement, self.profiles)


class GLEP73Conflict(base.Warning):
    """REQUIRED_USE constraints that can request the user to enable
    and disable the same flag simultaneously. This is a major issue
    for the auto-enforcing (since it is unclear which constraint should
    take priority), and it can cause confusing REQUIRED_USE mismatch
    messages for regular users."""

    __slots__ = ("category", "package", "version", "ci", "ei",
                 "cj", "ej", "profiles")
    threshold = base.versioned_feed

    def __init__(self, pkg, ci, ei, cj, ej, profiles):
        super(GLEP73Conflict, self).__init__()
        self._store_cpv(pkg)
        self.ci = ci
        self.ei = ei
        self.cj = cj
        self.ej = ej
        self.profiles = profiles

    @property
    def short_desc(self):
        return ('REQUIRED_USE can request conflicting states: ' +
                '[%s] requires [%s] while [%s] requires [%s]') % (
                ' && '.join('%s' % x for x in self.ci), self.ei,
                ' && '.join('%s' % x for x in self.cj), self.ej)


glep73_known_results = (GLEP73Syntax, GLEP73Immutability,
                        GLEP73Conflict)


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


def glep73_get_all_flags(requse):
    """Grab names of all flags used in the REQUIRED_USE constraint."""
    ret = set()
    for c in requse:
        if isinstance(c, ContainmentMatch):
            ret.update(c.vals)
        elif isinstance(c, Conditional):
            ret.update(glep73_get_all_flags(c))
            ret.update(glep73_get_all_flags((c.restriction,)))
        elif (isinstance(c, OrRestriction) or
              isinstance(c, JustOneRestriction) or
              isinstance(c, AtMostOneOfRestriction)):
            ret.update(glep73_get_all_flags(c))
        else:
            raise AssertionError('Unexpected item in REQUIRED_USE: %s' % (c,))

    return ret


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

    def negated(self):
        """Return the negated version of the flag."""
        return GLEP73Flag(self.name, negate=self.enabled)

    def __eq__(self, other):
        return self.name == other.name and self.enabled == other.enabled

    def __hash__(self):
        return hash((self.name, self.enabled))

    def __str__(self):
        return '%s%s' % ('' if self.enabled else '!', self.name)

    def __repr__(self):
        return 'GLEP73Flag("%s", negate=%s)' % (self.name, not self.enabled)


class immutability_sort_key(object):
    """Sorting key for immutability-based flag reordering defined
    in GLEP 73. Immutable flags that evaluate to true are moved to
    the beginning, those that evaluate to false are moved to
    the end and the remaining flags are left in the middle. Flags within
    the same class return the same key, so a stable sort will preserve
    their relative ordering."""

    __slots__ = ('immutables')

    def __init__(self, immutables):
        self.immutables = immutables

    def __call__(self, key):
        assert(isinstance(key, ContainmentMatch))
        assert(len(key.vals) == 1)
        name = next(iter(key.vals))

        v = self.immutables.get(name)
        if v is True:
            # forced go to the front
            return 0
        elif v is False:
            # masked go to the end
            return 2
        else:
            # normal go in the middle
            return 1


def glep73_flatten(requse, immutables={}):
    """Transform the REQUIRED_USE into flat constraints as described
    in GLEP 73."""
    sort_key = immutability_sort_key(immutables)

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

                # reorder according to immutability
                subitems = sorted(c.restrictions, key=sort_key)

                if not isinstance(c, AtMostOneOfRestriction):
                    # ^^ ( a b c ... ) -> || ( a b c ) ...
                    # || ( a b c ... ) -> [!b !c ...]? ( a )
                    yield (conditions + [GLEP73Flag(x, negate=True) for x in subitems[1:]],
                           GLEP73Flag(subitems[0]))
                if not isinstance(c, OrRestriction):
                    # ^^ ( a b c ... ) -> ... ?? ( a b c )
                    # ?? ( a b c ... ) -> a? ( !b !c ... ) b? ( !c ... ) ...
                    for i in range(0, len(subitems)-1):
                        new_cond = conditions + [GLEP73Flag(x) for x in subitems[i:i+1]]
                        for x in subitems[i+1:]:
                            yield (new_cond, GLEP73Flag(x, negate=True))
            else:
                raise AssertionError('Unknown item in REQUIRED_USE: %s' % (c,))

    return list(rec(requse, []))


def conditions_can_coexist(c1, c2):
    """Check whether the two conditions c1 and c2 can coexist, that is
    whether they both can evaluate to true simultaneously. It is assumed
    that this is true if the two conditions do not request the opposite
    states of the same flag."""
    for c1i in c1:
        if c1i.negated() in c2:
            return False
    return True


def strip_common_prefix(c1, c2):
    """Check if the conditions of two flattened constraint share common
    nodes on the condition graph. If they do, discard the common prefix
    and return the tuple with unique node sets for both."""
    # copy in order to avoid altering the original values
    c1 = list(c1)
    c2 = list(c2)
    while c1 and c2 and c1[0] is c2[0]:
        del c1[0]
        del c2[0]
    return (c1, c2)


def test_condition(c, flag_dict, accept_undefined):
    """Test whether the set of conditions C evaluates to true, with flag
    states defined by flag_dict (dict of flag name->bool). If the flag
    is not included in flag_dict and accept_undefined is true, it is
    assumed to match. If accept_undefined is false, it is assumed
    not to match."""
    for ci in c:
        v = flag_dict.get(ci.name)
        if v is None:
            if not accept_undefined:
                return False
        elif v != ci.enabled:
            return False
    return True


class ConflictingInitialFlags(ValueError):
    def __init__(self, flag):
        super(ConflictingInitialFlags, self).__init__(
                'Condition requires %s to be both true and false'
                % (flag,))
        self.flag = flag


def get_final_flags(constraints, initial_flags):
    """Evaluate the 'guaranteed' final flag state after processing
    constraints with the specified initial set of flags. The constraints
    will be processed in order, and the flag states will be altered
    only if the condition is guaranteed to match with already evaluated
    flag state. In other words, constraints with conditions depending
    on at least one flag whose value is undefined will be skipped."""
    # convert initial_flags to a dict
    flag_states = {}
    for f in initial_flags:
        if flag_states.setdefault(f.name, f.enabled) != f.enabled:
            raise ConflictingInitialFlags(f.name)

    # success cache is where we store ids of conditions that we
    # evaluated already
    success_cache = set()

    for c, e in constraints:
        # common prefix support:
        # if two constraints have a common prefix, the ids of their nodes
        # match; otherwise, the ids will always be different. therefore,
        # we can just dumbly prefix-match every next constraint against
        # the successes so far and strip them
        c = list(c)
        while c and id(c[0]) in success_cache:
            del c[0]

        # if all conditions evaluate to true (and there are no unmatched
        # flags), the effect will always apply
        if test_condition(c, flag_states, False):
            # store all the successes in the cache
            success_cache.update(id(ci) for ci in c)

            flag_states[e.name] = e.enabled

    return flag_states


def glep73_run_checks(requse, immutables):
    flattened = glep73_flatten(requse, immutables)

    for i, (ci, ei) in enumerate(flattened):
        # 1. immutability check
        for cix in ci:
            # if Ci,x is in immutables, and it evaluates to false,
            # the rule will never apply; if it is not in immutables,
            # we assume it can apply
            if immutables.get(cix.name, cix.enabled) != cix.enabled:
                break
        else:
            if immutables.get(ei.name, ei.enabled) != ei.enabled:
                yield partial(GLEP73Immutability,
                              condition=ci,
                              enforcement=ei)

        for cj, ej in flattened[i+1:]:
            cis, cjs = strip_common_prefix(ci, cj)

            # 2. conflict check:
            # two constraints (Ci, Ei); (Cj, Ej) conflict if:
            # a. Ei = !Ej, and
            # b. Ci and Cj can occur simultaneously.
            if ei == ej.negated() and conditions_can_coexist(cis, cjs):
                yield partial(GLEP73Conflict,
                              ci=ci, ei=ei,
                              cj=cj, ej=ej)
