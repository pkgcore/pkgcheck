from collections import defaultdict
from datetime import datetime
from itertools import chain

from snakeoil.klass import jit_attr
from snakeoil.strings import pluralism as _pl

from .. import base, git, results, sources
from . import GentooRepoCheck

day = 24*3600


class StableRequest(results.VersionedResult, results.Info):
    """Unstable package added over thirty days ago that could be stabilized."""

    def __init__(self, slot, keywords, age, **kwargs):
        super().__init__(**kwargs)
        self.slot = slot
        self.keywords = tuple(keywords)
        self.age = age

    @property
    def desc(self):
        return (
            f"slot({self.slot}) no change in {self.age} days for unstable "
            "keyword%s: [ %s ]" % (_pl(self.keywords), ', '.join(self.keywords))
        )


class StableRequestCheck(GentooRepoCheck):
    """Ebuilds that have sat unstable with no changes for over a month.

    By default, only triggered for arches with stable profiles. To check
    additional arches outside the stable set specify them manually using the
    -a/--arches option.

    Note that packages with no stable keywords won't trigger this at all.
    Instead they'll be caught by the UnstableOnly check.
    """
    scope = base.package_scope
    _source = (sources.PackageRepoSource, (), (('source', sources.UnmaskedRepoSource),))
    required_addons = (git.GitAddon,)
    known_results = frozenset([StableRequest])

    def __init__(self, *args, git_addon=None):
        super().__init__(*args)
        self.today = datetime.today()
        self._git_addon = git_addon

    @jit_attr
    def modified_repo(self):
        return self._git_addon.cached_repo(git.GitModifiedRepo)

    def feed(self, pkgset):
        # disable check when git repo parsing is disabled
        if self.modified_repo is None:
            return

        pkg_slotted = defaultdict(list)
        for pkg in pkgset:
            pkg_slotted[pkg.slot].append(pkg)

        pkg_keywords = set(chain.from_iterable(pkg.keywords for pkg in pkgset))
        stable_pkg_keywords = {x for x in pkg_keywords if x[0] not in {'-', '~'}}
        if stable_pkg_keywords:
            for slot, pkgs in sorted(pkg_slotted.items()):
                slot_keywords = set(chain.from_iterable(pkg.keywords for pkg in pkgs))
                stable_slot_keywords = slot_keywords.intersection(stable_pkg_keywords)
                for pkg in reversed(pkgs):
                    # skip unkeyworded/live pkgs
                    if not pkg.keywords:
                        continue

                    # stop scanning pkgs if one newer than 30 days has stable keywords
                    # from the stable arches set
                    if set(pkg.keywords).intersection(stable_pkg_keywords):
                        break

                    try:
                        match = self.modified_repo.match(pkg.versioned_atom)[0]
                    except IndexError:
                        # probably an uncommitted, local ebuild... skipping
                        continue
                    added = datetime.strptime(match.date, '%Y-%m-%d')
                    days_old = (self.today - added).days
                    if days_old >= 30:
                        pkg_stable_keywords = {x.lstrip('~') for x in pkg.keywords}
                        if stable_slot_keywords:
                            keywords = stable_slot_keywords.intersection(pkg_stable_keywords)
                        else:
                            keywords = stable_pkg_keywords.intersection(pkg_stable_keywords)
                        keywords = sorted('~' + x for x in keywords)
                        yield StableRequest(slot, keywords, days_old, pkg=pkg)
                        break
