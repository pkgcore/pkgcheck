from collections import defaultdict
from itertools import chain
import re

from pkgcore.ebuild import restricts
from pkgcore.restrictions import packages

from .. import base, sources


class MissingAccountIdentifier(base.VersionedResult, base.Warning):
    """UID/GID can not be found in account package."""

    __slots__ = ('var',)

    def __init__(self, pkg, var):
        super().__init__(pkg)
        self.var = var

    @property
    def short_desc(self):
        return f"unable to determine the value of {self.var} variable"


class ConflictingAccountIdentifiers(base.Error):
    """Same UID/GID is used by multiple packages."""

    __slots__ = ("kind", "identifier", "pkgs")

    threshold = base.repository_feed

    def __init__(self, kind, identifier, pkgs):
        super().__init__()
        self.kind = kind
        self.identifier = identifier
        self.pkgs = tuple(sorted(p.cpvstr for p in pkgs))

    @property
    def short_desc(self):
        return (
            f"conflicting {self.kind} id {self.identifier} usage: "
            f"[ {', '.join(self.pkgs)} ]")


class OutsideRangeAccountIdentifier(base.VersionedResult, base.Error):
    """UID/GID outside allowed allocation range."""

    __slots__ = ("kind", "identifier")

    def __init__(self, pkg, kind, identifier):
        super().__init__(pkg)
        self.kind = kind
        self.identifier = identifier

    @property
    def short_desc(self):
        return (
            f"{self.kind} id {self.identifier} outside permitted "
            f"static allocation range (0..499, 60001+)")


class AcctCheck(base.Check):
    """Various checks for acct-* packages.

    Verify that acct-* packages do not use conflicting, invalid or out-of-range
    UIDs/GIDs.
    """

    scope = base.repository_scope
    feed_type = base.versioned_feed
    source = (sources.RestrictionRepoSource, (packages.OrRestriction(*(
            restricts.CategoryDep('acct-user'), restricts.CategoryDep('acct-group'))),))
    known_results = (
        MissingAccountIdentifier, ConflictingAccountIdentifiers,
        OutsideRangeAccountIdentifier,
    )

    def __init__(self, options):
        super().__init__(options)
        self.id_re = re.compile(
            r'ACCT_(?P<var>USER|GROUP)_ID=(?P<quot>[\'"]?)(?P<id>[0-9]+)(?P=quot)')
        self.seen_uids = defaultdict(lambda: defaultdict(list))
        self.seen_gids = defaultdict(lambda: defaultdict(list))
        self.category_map = {
            'acct-user': (self.seen_uids, 'USER', (65534,)),
            'acct-group': (self.seen_gids, 'GROUP', (65533, 65534)),
        }

    def feed(self, pkg):
        try:
            seen_id_map, expected_var, extra_allowed_ids = self.category_map[pkg.category]
        except KeyError:
            return

        for l in pkg.ebuild.text_fileobj():
            m = self.id_re.match(l)
            if m is not None:
                if m.group('var') == expected_var:
                    found_id = int(m.group('id'))
                    break
        else:
            return (MissingAccountIdentifier(pkg, f"ACCT_{expected_var}_ID"),)

        # all UIDs/GIDs must be in <500, with special exception
        # of nobody/nogroup which use 65534/65533
        if found_id >= 500 and found_id not in extra_allowed_ids:
            return (OutsideRangeAccountIdentifier(pkg, expected_var.lower(), found_id),)

        seen_id_map[found_id][pkg.key].append(pkg)

    def finish(self):
        # report overlapping ID usage
        for seen, expected_var, _ids in self.category_map.values():
            for found_id, pkgs in sorted(seen.items()):
                if len(pkgs) > 1:
                    conflicting_pkgs = chain.from_iterable(pkgs.values())
                    yield ConflictingAccountIdentifiers(
                        expected_var.lower(), found_id, conflicting_pkgs)
