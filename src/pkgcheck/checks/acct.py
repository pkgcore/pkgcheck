"""Various checks for acct-group and acct-user packages."""

import re
from collections import defaultdict
from configparser import ConfigParser
from functools import partial
from itertools import chain

from pkgcore.ebuild import restricts
from pkgcore.restrictions import packages
from snakeoil.osutils import pjoin

from .. import results, sources
from . import GentooRepoCheck, RepoCheck, SkipCheck


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
        pkgs = ", ".join(self.pkgs)
        return f"conflicting {self.kind} id {self.identifier} usage: [ {pkgs} ]"


class OutsideRangeAccountIdentifier(results.VersionResult, results.Error):
    """UID/GID outside allowed allocation range.

    To view the range accepted for this repository, look at the file
    ``metadata/qa-policy.conf`` in the section ``user-group-ids``.
    """

    def __init__(self, kind, identifier, **kwargs):
        super().__init__(**kwargs)
        self.kind = kind
        self.identifier = identifier

    @property
    def desc(self):
        return f"{self.kind} id {self.identifier} outside permitted " f"static allocation range"


class AcctCheck(GentooRepoCheck, RepoCheck):
    """Various checks for acct-* packages.

    Verify that acct-* packages do not use conflicting, invalid or out-of-range
    UIDs/GIDs. This check uses a special file ``metadata/qa-policy.conf``
    located within the repository. It should contain a ``user-group-ids``
    section containing two keys: ``uid-range`` and ``gid-range``, which consist
    of a comma separated list, either ``<n>`` for a single value or ``<m>-<n>``
    for a range of values (including both ends). In case this file doesn't
    exist or is wrongly defined, this check is skipped.
    """

    _restricted_source = (
        sources.RestrictionRepoSource,
        (
            packages.OrRestriction(
                *(restricts.CategoryDep("acct-user"), restricts.CategoryDep("acct-group"))
            ),
        ),
    )
    _source = (sources.RepositoryRepoSource, (), (("source", _restricted_source),))
    known_results = frozenset(
        [
            MissingAccountIdentifier,
            ConflictingAccountIdentifiers,
            OutsideRangeAccountIdentifier,
        ]
    )

    def __init__(self, *args):
        super().__init__(*args)
        self.id_re = re.compile(
            r'ACCT_(?P<var>USER|GROUP)_ID=(?P<quot>[\'"]?)(?P<id>[0-9]+)(?P=quot)'
        )
        self.seen_uids = defaultdict(partial(defaultdict, list))
        self.seen_gids = defaultdict(partial(defaultdict, list))
        uid_range, gid_range = self.load_ids_from_configuration(self.options.target_repo)
        self.category_map = {
            "acct-user": (self.seen_uids, "USER", tuple(uid_range)),
            "acct-group": (self.seen_gids, "GROUP", tuple(gid_range)),
        }

    def parse_config_id_range(self, config: ConfigParser, config_key: str):
        id_ranges = config["user-group-ids"].get(config_key, None)
        if not id_ranges:
            raise SkipCheck(self, f"metadata/qa-policy.conf: missing value for {config_key}")
        try:
            for id_range in map(str.strip, id_ranges.split(",")):
                start, *end = map(int, id_range.split("-", maxsplit=1))
                if len(end) == 0:
                    yield range(start, start + 1)
                else:
                    yield range(start, end[0] + 1)
        except ValueError:
            raise SkipCheck(self, f"metadata/qa-policy.conf: invalid value for {config_key}")

    def load_ids_from_configuration(self, repo):
        config = ConfigParser()
        if not config.read(pjoin(repo.location, "metadata", "qa-policy.conf")):
            raise SkipCheck(self, "failed loading 'metadata/qa-policy.conf'")
        if "user-group-ids" not in config:
            raise SkipCheck(self, "metadata/qa-policy.conf: missing section user-group-ids")
        return self.parse_config_id_range(config, "uid-range"), self.parse_config_id_range(
            config, "gid-range"
        )

    def feed(self, pkg):
        try:
            seen_id_map, expected_var, allowed_ids = self.category_map[pkg.category]
        except KeyError:
            return

        for line in pkg.ebuild.text_fileobj():
            m = self.id_re.match(line)
            if m is not None and m.group("var") == expected_var:
                found_id = int(m.group("id"))
                break
        else:
            yield MissingAccountIdentifier(f"ACCT_{expected_var}_ID", pkg=pkg)
            return

        if not any(found_id in id_range for id_range in allowed_ids):
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
