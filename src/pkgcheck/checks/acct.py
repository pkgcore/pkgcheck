"""Various checks for acct-group and acct-user packages."""

import re
from collections import defaultdict
from functools import partial
from itertools import chain

from pkgcore.ebuild import restricts
from pkgcore.restrictions import packages

from .. import results, sources
from . import GentooRepoCheck, RepoCheck


class MissingAccountIdentifier(results.VersionResult, results.Warning):
    """UID/GID can not be found in account package."""

    def __init__(self, var, **kwargs):
        super().__init__(**kwargs)
        self.var = var

    @property
    def desc(self):
        return f"unable to determine the value of {self.var} variable"


class ConflictingAccountIdentifiers(results.Error):
    """Same UID/GID is used by multiple packages."""

    def __init__(self, kind, identifier, pkgs):
        super().__init__()
        self.kind = kind
        self.identifier = identifier
        self.pkgs = tuple(pkgs)

    @property
    def desc(self):
        return (
            f"conflicting {self.kind} id {self.identifier} usage: "
            f"[ {', '.join(self.pkgs)} ]")


class OutsideRangeAccountIdentifier(results.VersionResult, results.Error):
    """UID/GID outside allowed allocation range."""

    def __init__(self, kind, identifier, **kwargs):
        super().__init__(**kwargs)
        self.kind = kind
        self.identifier = identifier

    @property
    def desc(self):
        return (
            f"{self.kind} id {self.identifier} outside permitted "
            f"static allocation range (0..499, 60001+)")


class AcctCheck(GentooRepoCheck, RepoCheck):
    """Various checks for acct-* packages.

    Verify that acct-* packages do not use conflicting, invalid or out-of-range
    UIDs/GIDs.
    """

    _restricted_source = (sources.RestrictionRepoSource, (packages.OrRestriction(*(
        restricts.CategoryDep('acct-user'), restricts.CategoryDep('acct-group'))),))
    _source = (sources.RepositoryRepoSource, (), (('source', _restricted_source),))
    known_results = frozenset([
        MissingAccountIdentifier, ConflictingAccountIdentifiers,
        OutsideRangeAccountIdentifier,
    ])

    def __init__(self, *args):
        super().__init__(*args)
        self.id_re = re.compile(
            r'ACCT_(?P<var>USER|GROUP)_ID=(?P<quot>[\'"]?)(?P<id>[0-9]+)(?P=quot)')
        self.seen_uids = defaultdict(partial(defaultdict, list))
        self.seen_gids = defaultdict(partial(defaultdict, list))
        self.category_map = {
            'acct-user': (self.seen_uids, 'USER', (65534,)),
            'acct-group': (self.seen_gids, 'GROUP', (65533, 65534)),
        }

    def feed(self, pkg):
        try:
            seen_id_map, expected_var, extra_allowed_ids = self.category_map[pkg.category]
        except KeyError:
            return

        for line in pkg.ebuild.text_fileobj():
            m = self.id_re.match(line)
            if m is not None and m.group('var') == expected_var:
                found_id = int(m.group('id'))
                break
        else:
            yield MissingAccountIdentifier(f"ACCT_{expected_var}_ID", pkg=pkg)
            return

        # all UIDs/GIDs must be in <750, with special exception
        # of nobody/nogroup which use 65534/65533
        if found_id >= 750 and found_id not in extra_allowed_ids:
            yield OutsideRangeAccountIdentifier(expected_var.lower(), found_id, pkg=pkg)
            return

        seen_id_map[found_id][pkg.key].append(pkg)

    def finish(self):
        # report overlapping ID usage
        for seen, expected_var, _ids in self.category_map.values():
            for found_id, pkgs in sorted(seen.items()):
                if len(pkgs) > 1:
                    pkgs = (x.cpvstr for x in sorted(chain.from_iterable(pkgs.values())))
                    yield ConflictingAccountIdentifiers(expected_var.lower(), found_id, pkgs)
