import itertools

from pkgcore.ebuild.atom import atom
from snakeoil.sequences import iflatten_instance
from snakeoil.strings import pluralism

from .. import results
from . import Check


IUSE_PREFIX = "ruby_targets_"


class RubyCompatUpdate(results.VersionResult, results.Info):
    """``USE_RUBY`` can be updated to support newer ruby version(s)."""

    def __init__(self, updates, **kwargs):
        super().__init__(**kwargs)
        self.updates = tuple(updates)

    @property
    def desc(self):
        s = pluralism(self.updates)
        updates = ", ".join(self.updates)
        return f"USE_RUBY update{s} available: {updates}"


class RubyCompatCheck(Check):
    """Check ruby ebuilds for possible ``USE_RUBY`` updates.

    Supports ebuilds inheriting ``ruby-ng``.
    """

    known_results = frozenset({RubyCompatUpdate})

    whitelist_categories = frozenset({"virtual"})

    def __init__(self, *args):
        super().__init__(*args)
        repo = self.options.target_repo
        # sorter for ruby targets leveraging USE_EXPAND flag ordering from repo
        self.sorter = repo.use_expand_sorter("ruby_targets")

        # determine available USE_RUBY use flags
        targets = []
        for target, _desc in repo.use_expand_desc.get(IUSE_PREFIX[:-1], ()):
            if target[len(IUSE_PREFIX) :].startswith("ruby"):
                targets.append(target[len(IUSE_PREFIX) :])
        self.multi_targets = tuple(sorted(targets, key=self.sorter))

    def ruby_deps(self, deps, prefix):
        for dep in (x for x in deps if x.use):
            for x in dep.use:
                if x.startswith(("-", "!")):
                    continue
                if x.startswith(prefix):
                    yield dep.no_usedeps
                    break

    def deps(self, pkg):
        """Set of dependencies for a given package's attributes."""
        return {
            p
            for attr in (x.lower() for x in pkg.eapi.dep_keys)
            for p in iflatten_instance(getattr(pkg, attr), atom)
            if not p.blocks
        }

    def feed(self, pkg):
        if pkg.category in self.whitelist_categories or "ruby-ng" not in pkg.inherited:
            return

        deps = self.deps(pkg)

        try:
            # determine the latest supported ruby version
            latest_target = sorted(
                (
                    f"ruby{x.slot.replace('.', '')}"
                    for x in deps
                    if x.key == "dev-lang/ruby" and x.slot is not None
                ),
                key=self.sorter,
            )[-1]
        except IndexError:
            return

        # determine ruby impls to target
        targets = set(
            itertools.takewhile(lambda x: x != latest_target, reversed(self.multi_targets))
        )

        if targets:
            try:
                # determine if deps support missing ruby targets
                for dep in self.ruby_deps(deps, IUSE_PREFIX):
                    # TODO: use query caching for repo matching?
                    latest = sorted(self.options.search_repo.match(dep))[-1]
                    targets.intersection_update(
                        f"ruby{x.rsplit('ruby', 1)[-1]}"
                        for x in latest.iuse_stripped
                        if x.startswith(IUSE_PREFIX)
                    )
                    if not targets:
                        return
            except IndexError:
                return

            yield RubyCompatUpdate(sorted(targets, key=self.sorter), pkg=pkg)
