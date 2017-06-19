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
