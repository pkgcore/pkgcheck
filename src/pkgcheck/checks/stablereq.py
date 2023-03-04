from collections import defaultdict
from datetime import datetime

from snakeoil.cli import arghparse
from snakeoil.strings import pluralism

from .. import addons, results, sources
from . import GentooRepoCheck


class StableRequest(results.VersionResult, results.Info):
    """Unstable ebuild with no changes for over 30 days."""

    def __init__(self, slot, keywords, age, **kwargs):
        super().__init__(**kwargs)
        self.slot = slot
        self.keywords = tuple(keywords)
        self.age = int(age)

    @property
    def desc(self):
        s = pluralism(self.keywords)
        keywords = ", ".join(self.keywords)
        return (
            f"slot({self.slot}) no change in {self.age} days "
            f"for unstable keyword{s}: [ {keywords} ]"
        )


class StableRequestCheck(GentooRepoCheck):
    """Scan for unstable ebuilds with no changes for over 30 days.

    By default, only triggered for arches with stable profiles. To check
    additional arches outside the stable set specify them manually using the
    -a/--arches option.

    Note that packages with no stable keywords won't trigger this at all.
    Instead they'll be caught by the UnstableOnly check.
    """

    _source = (sources.PackageRepoSource, (), (("source", sources.UnmaskedRepoSource),))
    required_addons = (addons.git.GitAddon,)
    known_results = frozenset([StableRequest])

    @staticmethod
    def mangle_argparser(parser):
        parser.plugin.add_argument(
            "--stabletime",
            metavar="DAYS",
            dest="stable_time",
            default=30,
            type=arghparse.positive_int,
            help="set number of days before stabilisation",
            docs="""
                An integer number of days before a package version is flagged by
                StableRequestCheck. Defaults to 30 days.
            """,
        )

    def __init__(self, *args, git_addon):
        super().__init__(*args)
        self.today = datetime.today()
        self.modified_repo = git_addon.cached_repo(addons.git.GitModifiedRepo)

    def feed(self, pkgset):
        pkg_slotted = defaultdict(list)
        pkg_keywords = set()
        # ebuilds without keywords are ignored
        for pkg in (x for x in pkgset if x.keywords):
            pkg_slotted[pkg.slot].append(pkg)
            pkg_keywords.update(pkg.keywords)

        if stable_pkg_keywords := {x for x in pkg_keywords if x[0] not in {"-", "~"}}:
            keyworded_pkg_keywords = {"~" + x for x in stable_pkg_keywords}
            for slot, pkgs in sorted(pkg_slotted.items()):
                slot_keywords = set().union(*(pkg.keywords for pkg in pkgs))
                stable_slot_keywords = slot_keywords.intersection(stable_pkg_keywords)
                for pkg in reversed(pkgs):
                    # stop if stable keywords are found
                    if stable_pkg_keywords.intersection(pkg.keywords):
                        break

                    # stop if not keyworded for stable
                    if not keyworded_pkg_keywords.intersection(pkg.keywords):
                        break

                    try:
                        match = next(self.modified_repo.itermatch(pkg.versioned_atom))
                    except StopIteration:
                        # probably an uncommitted, local ebuild... skipping
                        continue

                    added = datetime.fromtimestamp(match.time)
                    days_old = (self.today - added).days
                    if days_old >= self.options.stable_time:
                        pkg_stable_keywords = {x.lstrip("~") for x in pkg.keywords}
                        if stable_slot_keywords:
                            keywords = stable_slot_keywords.intersection(pkg_stable_keywords)
                        else:
                            keywords = stable_pkg_keywords.intersection(pkg_stable_keywords)
                        keywords = sorted("~" + x for x in keywords)
                        yield StableRequest(slot, keywords, days_old, pkg=pkg)
                        break
