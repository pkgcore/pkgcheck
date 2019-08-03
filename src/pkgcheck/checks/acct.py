import re

from collections import defaultdict
from itertools import groupby
from operator import attrgetter, itemgetter

from .. import base


class MissingAccountIdentifier(base.Warning):
    """UID/GID can not be found in account package."""

    __slots__ = ("category", "package", "version", "var")

    threshold = base.versioned_feed

    def __init__(self, pkg, var):
        super().__init__()
        self._store_cpv(pkg)
        self.var = var

    @property
    def short_desc(self):
        return (
            f"unable to determine the value of {self.var} variable")


class ConflictingAccountIdentifier(base.Error):
    """Same UID/GID is used by two different users/groups."""

    __slots__ = ("category", "package", "version", "kind", "identifier", "others")

    threshold = base.versioned_feed

    _sorter = staticmethod(itemgetter(0))

    def __init__(self, pkg, kind, identifier, others):
        super().__init__()
        self._store_cpv(pkg)
        self.kind = kind
        self.identifier = identifier
        self.others = tuple(sorted(p.cpvstr for p in others))

    @property
    def short_desc(self):
        return (
            f"{self.kind} id {self.identifier} is already used by other "
            f"{self.kind}: ({', '.join(self.others)})")


class OutOfRangeAccountIdentifier(base.Error):
    """UID/GID outside allowed allocation range."""

    __slots__ = ("category", "package", "version", "kind", "identifier")

    threshold = base.versioned_feed

    def __init__(self, pkg, kind, identifier):
        super().__init__()
        self._store_cpv(pkg)
        self.kind = kind
        self.identifier = identifier

    @property
    def short_desc(self):
        return (
            f"{self.kind} id {self.identifier} is outside the permitted "
            f"static allocation range (0..499, 60001+)")


class AcctCheck(base.Template):
    """Check for acct-* packages.

    Verify that acct-* packages do not use conflicting, invalid or out-of-range
    UIDs/GIDs.
    """

    scope = base.repository_scope
    feed_type = base.package_feed
    known_results = (MissingAccountIdentifier, ConflictingAccountIdentifier,
                     OutOfRangeAccountIdentifier)

    repo_grabber = attrgetter("repo")

    def __init__(self, options):
        super().__init__(options)
        self.id_re = re.compile(
            r'ACCT_(?P<var>USER|GROUP)_ID=(?P<quot>[\'"]?)(?P<id>[0-9]+)(?P=quot)')
        self.seen_uids = defaultdict(lambda: defaultdict(list))
        self.seen_gids = defaultdict(lambda: defaultdict(list))

    def feed(self, full_pkgset):
        # TODO: can we filter this earlier?
        if full_pkgset[0].category == 'acct-user':
            expected_var = 'USER'
            seen_var = self.seen_uids
            extra_allowed_ids = (65534,)
        elif full_pkgset[0].category == 'acct-group':
            expected_var = 'GROUP'
            seen_var = self.seen_gids
            extra_allowed_ids = (65533, 65534)
        else:
            return

        # sort it by repo.
        for repo, pkgset in groupby(full_pkgset, self.repo_grabber):
            for pkg in pkgset:
                for l in pkg.ebuild.text_fileobj():
                    m = self.id_re.match(l)
                    if m is not None:
                        if m.group('var') == expected_var:
                            found_id = m.group('id')
                            break
                else:
                    yield MissingAccountIdentifier(pkg,
                        f"ACCT_{expected_var}_ID")
                    continue

                seen_list = seen_var[repo][found_id]
                for other in seen_list:
                    # ignore other versions of the same package
                    if pkg.key != other.key:
                        yield ConflictingAccountIdentifier(
                            pkg, expected_var.lower(), found_id, seen_list)
                seen_list.append(pkg)

                found_id = int(found_id)
                # all UIDs/GIDs must be in <500, with special exception
                # of nobody/nogroup which use 65534/65533
                if found_id >= 500 and found_id not in extra_allowed_ids:
                    yield OutOfRangeAccountIdentifier(
                        pkg, expected_var.lower(), found_id)
