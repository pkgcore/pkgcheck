from collections import defaultdict
from datetime import datetime
from itertools import chain
import time

from snakeoil.strings import pluralism as _pl

from .. import addons, base

day = 24*3600


class StableRequest(base.Warning):
    """Unstable package added over thirty days ago that could be stabilized."""

    __slots__ = ("category", "package", "version", "keywords", "period")

    threshold = base.versioned_feed

    def __init__(self, pkg, keywords, period):
        super().__init__()
        self._store_cpv(pkg)
        self.slot = pkg.slot
        self.keywords = tuple(keywords)
        self.period = period

    @property
    def short_desc(self):
        return (
            f"slot({self.slot}) no change in {self.period} days for unstable "
            "keyword%s: [ %s ]" % (_pl(self.keywords), ', '.join(self.keywords))
        )


class StableRequestCheck(base.Template):
    """Ebuilds that have sat unstable with no changes for over a month.

    By default, only triggered for arches with stable profiles. To check
    additional arches outside the stable set specify them manually using the
    -a/--arches option.

    Note that packages with no stable keywords won't trigger this at all.
    Instead they'll be caught by the UnstableOnly check.
    """
    feed_type = base.package_feed
    required_addons = (addons.StableArchesAddon, addons.GitAddon)
    known_results = (StableRequest,)

    def __init__(self, options, stable_arches=None, git_addon=None, staleness=int(day*30)):
        super().__init__(options)
        self.staleness = staleness
        self.start_time = None
        self.arches = frozenset(x.lstrip("~") for x in options.stable_arches)
        self.today = datetime.today()
        self.added_repo = git_addon.cached_repo(addons.GitAddedRepo)

    def start(self, reporter):
        self.start_time = time.time()

    def feed(self, pkgset, reporter):
        # disable check when git repo parsing is disabled
        if self.added_repo is None:
            return

        pkg_slotted = defaultdict(list)
        for pkg in pkgset:
            pkg_slotted[pkg.slot].append(pkg)

        pkg_keywords = set(chain.from_iterable(pkg.keywords for pkg in pkgset))
        stable_pkg = bool(pkg_keywords.intersection(self.arches))
        if stable_pkg:
            for slot, pkgs in sorted(pkg_slotted.items()):
                slot_keywords = set(chain.from_iterable(pkg.keywords for pkg in pkgs))
                stable_slot_keywords = slot_keywords.intersection(self.arches)
                for pkg in reversed(pkgs):
                    # skip unkeyworded/live pkgs
                    if not pkg.keywords:
                        continue

                    # stop scanning pkgs if one newer than 30 days has stable keywords
                    # from the stable arches set
                    stable_keywords = set(pkg.keywords).intersection(self.arches)
                    if stable_keywords:
                        break

                    try:
                        match = self.added_repo.match(pkg.versioned_atom)[0]
                    except IndexError:
                        # probably an uncommitted, local ebuild... skipping
                        continue
                    added = self.added_repo.pkg_date(match)
                    added = datetime.strptime(added, '%Y-%m-%d')
                    days_old = (self.today - added).days
                    if days_old >= 30:
                        keywords = sorted('~' + x for x in stable_slot_keywords)
                        if keywords:
                            reporter.add_report(StableRequest(pkg, keywords, days_old))
                            break
