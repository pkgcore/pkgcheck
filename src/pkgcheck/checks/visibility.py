from datetime import datetime
import os
import pickle
import re
import subprocess

from pkgcore.ebuild.atom import atom
from pkgcore.repository.util import SimpleTree
from pkgcore.restrictions.packages import OrRestriction

from snakeoil import klass
from snakeoil.cli.exceptions import UserException
from snakeoil.iterables import caching_iter
from snakeoil.osutils import pjoin
from snakeoil.process.spawn import spawn_get_output
from snakeoil.sequences import stable_unique, iflatten_instance, iflatten_func
from snakeoil.strings import pluralism as _pl

from .. import base, addons


class FakeConfigurable(object):
    "Package wrapper binding profile data."""

    configurable = True
    __slots__ = ('use', 'iuse', '_forced_use', '_masked_use', '_pkg_use', '_raw_pkg', '_profile')

    def __init__(self, pkg, profile):
        object.__setattr__(self, '_raw_pkg', pkg)
        object.__setattr__(self, '_profile', profile)

        object.__setattr__(
            self, '_forced_use', self._profile.forced_use.pull_data(self._raw_pkg))
        object.__setattr__(
            self, '_masked_use', self._profile.masked_use.pull_data(self._raw_pkg))
        object.__setattr__(
            self, '_pkg_use', self._profile.pkg_use.pull_data(self._raw_pkg))
        use_defaults = set(x[1:] for x in pkg.iuse if x[0] == '+')
        enabled_use = (use_defaults | profile.use | self._pkg_use | self._forced_use) - self._masked_use
        object.__setattr__(
            self, 'use', frozenset(enabled_use & (profile.iuse_effective | pkg.iuse_effective)))
        object.__setattr__(
            self, 'iuse', frozenset(profile.iuse_effective.union(pkg.iuse_stripped)))

    def request_enable(self, attr, *vals):
        if attr != 'use':
            return False

        set_vals = frozenset(vals)
        if not set_vals.issubset(self.iuse):
            # requested a flag that doesn't exist in iuse
            return False

        # if any of the flags are in masked_use, it's a no go.
        return set_vals.isdisjoint(self._masked_use)

    def request_disable(self, attr, *vals):
        if attr != 'use':
            return False

        set_vals = frozenset(vals)
        if not set_vals.issubset(self.iuse):
            # requested a flag that doesn't exist in iuse
            return False

        # if any of the flags are forced_use, it's a no go.
        return set_vals.isdisjoint(self._forced_use)

    def rollback(self, point=0):
        return True

    def changes_count(self):
        return 0

    __getattr__ = klass.GetAttrProxy("_raw_pkg")

    def __setattr__(self, attr, val):
        raise AttributeError(self, 'is immutable')

class _BlockMemoryExhaustion(Exception):
    pass


# This is fast path code, hence the seperated implementations.
if getattr(atom, '_TRANSITIVE_USE_ATOM_BUG_IS_FIXED', False):
    def _eapi2_flatten(val, atom_kls=atom, transitive_use_atom=atom._transitive_use_atom):
        return isinstance(val, atom_kls) and not isinstance(val, transitive_use_atom)
else:
    def _eapi2_flatten(val, atom_kls=atom, transitive_use_atom=atom._transitive_use_atom):
        if isinstance(val, transitive_use_atom):
            if len([x for x in val.use if x.endswith("?")]) > 16:
                raise _BlockMemoryExhaustion(val)
        return isinstance(val, atom_kls) and not isinstance(val, transitive_use_atom)


def visit_atoms(pkg, stream):
    if not pkg.eapi.options.transitive_use_atoms:
        return iflatten_instance(stream, atom)
    return iflatten_func(stream, _eapi2_flatten)


def strip_atom_use(inst):
    if not inst.use:
        return inst
    if '=*' == inst.op:
        s = f'={inst.cpvstr}*'
    else:
        s = inst.op + inst.cpvstr
    if inst.blocks:
        s = '!' + s
        if not inst.blocks_temp_ignorable:
            s = '!' + s
    if inst.slot:
        s += f':{inst.slot}'
    return atom(s)


class GitRepo(object):

    def __init__(self, repo_path, commit):
        self.path = repo_path
        self.commit = commit
        self.pkg_map = self._process_git_repo()

    def update(self, commit):
        self._process_git_repo(self.pkg_map, self.commit)
        self.commit = commit

    def _process_git_repo(self, pkg_map=None, commit=None):
        cmd = ['git', 'log', '--diff-filter=D', '--summary', '--date=short', '--reverse']
        if commit:
            cmd.append(f'{commit}..')
        if pkg_map is None:
            pkg_map = {}
        ebuild_regex = re.compile(r'^(.*)/(.*)/(.*)\.ebuild$')
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, cwd=self.path)
        line = process.stdout.readline().strip().decode()
        while True:
            if not line.startswith('commit '):
                raise RuntimeError(f'unknown git log output: {line!r}')
            commit = line[7:].strip()
            # author
            process.stdout.readline()
            # date
            line = process.stdout.readline().strip().decode()
            if not line.startswith('Date:'):
                raise RuntimeError(f'unknown git log output: {line!r}')
            date = line[5:].strip()

            while line and not line.startswith('commit '):
                line = process.stdout.readline().decode()
                if line.startswith(' delete mode '):
                    path = line.rsplit(' ', 1)[1]
                    match = ebuild_regex.match(path)
                    if match:
                        category = match.group(1)
                        pkgname = match.group(2)
                        pkg = match.group(3)
                        a = atom(f'={category}/{pkg}')
                        pkg_map.setdefault(
                            category, {}).setdefault(pkgname, []).append((a.fullver, date))
            if not line:
                break
        return pkg_map


class HistoricalRepo(SimpleTree):

    def _get_versions(self, cp_key):
        return tuple(version for version, date in self.cpv_dict[cp_key[0]][cp_key[1]])

    def removal_date(self, pkg):
        for version, date in self.cpv_dict[pkg.category][pkg.package]:
            if version == pkg.fullver:
                return date


class VisibleVcsPkg(base.Error):
    """Package is VCS-based, but visible."""

    __slots__ = ("category", "package", "version", "profile", "arch")

    threshold = base.versioned_feed

    def __init__(self, pkg, arch, profile):
        super().__init__()
        self._store_cpv(pkg)
        self.arch = arch.lstrip("~")
        self.profile = profile

    @property
    def short_desc(self):
        return f"VCS version visible for arch {self.arch}, profile {self.profile}"


class OutdatedBlocker(base.Warning):
    """Blocker dependency removed more than two years ago from the tree."""

    __slots__ = ("category", "package", "version", "attr", "atom", "age")

    threshold = base.versioned_feed

    def __init__(self, pkg, attr, atom, age):
        super().__init__()
        self._store_cpv(pkg)
        self.attr = attr
        self.atom = atom
        self.age = age

    @property
    def short_desc(self):
        return (
            f"depset {self.attr}: outdated blocker '{self.atom}': "
            f'last matching version removed {self.age} years ago'
        )


class NonExistentDeps(base.Warning):
    """No matches exist for a depset element."""

    __slots__ = ("category", "package", "version", "attr", "atoms")

    threshold = base.versioned_feed

    def __init__(self, pkg, attr, nonexistent_atoms):
        super().__init__()
        self._store_cpv(pkg)
        self.attr = attr
        self.atoms = tuple(map(str, nonexistent_atoms))

    @property
    def short_desc(self):
        return "depset %s: nonexistent dep%s: [ %s ]" % (
            self.attr, _pl(self.atoms), ', '.join(self.atoms))


class UncheckableDep(base.Warning):
    """Given dependency cannot be checked due to the number of transitive use deps in it."""

    __slots__ = ("category", "package", "version", "attr")

    threshold = base.versioned_feed

    def __init__(self, pkg, attr):
        super().__init__()
        self._store_cpv(pkg)
        self.attr = attr

    @property
    def short_desc(self):
        return f"depset {self.attr}: could not be checked due to pkgcore limitation"


class NonsolvableDeps(base.Error):
    """No potential solution for a depset attribute."""

    __slots__ = ("category", "package", "version", "attr", "profile",
                 "keyword", "potentials")

    threshold = base.versioned_feed

    def __init__(self, pkg, attr, keyword, profile, horked):
        super().__init__()
        self._store_cpv(pkg)
        self.attr = attr
        self.profile = profile
        self.keyword = keyword
        self.potentials = tuple(map(str, stable_unique(horked)))

    @property
    def short_desc(self):
        return \
            f"nonsolvable depset({self.attr}) keyword({self.keyword}) " \
            f"profile ({self.profile}): solutions: [ {', '.join(self.potentials)} ]"


class VisibilityReport(base.Template):
    """Visibility dependency scans.

    Check that at least one solution is possible for a pkg, checking all
    profiles (defined by arch.list) visibility modifiers per stable/unstable
    keyword.
    """

    feed_type = base.versioned_feed
    required_addons = (
        addons.QueryCacheAddon, addons.ProfileAddon,
        addons.EvaluateDepSetAddon)
    known_results = (VisibleVcsPkg, OutdatedBlocker, NonExistentDeps, NonsolvableDeps)

    def __init__(self, options, query_cache, profiles, depset_cache):
        super().__init__(options)
        self.query_cache = query_cache.query_cache
        self.depset_cache = depset_cache
        self.profiles = profiles

        ret, out = spawn_get_output(
            ['git', 'rev-parse', 'HEAD'], cwd=options.target_repo.location)
        if ret != 0:
            self.existence_repo = None
        else:
            commit = out[0].strip()

            # try loading historical repo data
            cache_file = pjoin(options.cache_dir, 'git_repo.pickle')
            cache_repo = True
            try:
                with open(cache_file, 'rb') as f:
                    git_repo = pickle.load(f)
                    if commit != git_repo.commit:
                        git_repo.update(commit)
                    else:
                        cache_repo = False
            except (EOFError, FileNotFoundError):
                git_repo = GitRepo(options.target_repo.location, commit)

            self.existence_repo = HistoricalRepo(git_repo.pkg_map, repo_id='historical')
            # dump historical repo data
            if cache_repo:
                try:
                    with open(cache_file, 'wb+') as f:
                        pickle.dump(git_repo, f)
                except IOError as e:
                    msg = f'failed dumping git pkg repo: {cache_file!r}: {e.strerror}'
                    if not options.forced_cache:
                        logger.warn(msg)
                    else:
                        raise UserException(msg)


    def feed(self, pkg, reporter):
        # query_cache gets caching_iter partial repo searches shoved into it-
        # reason is simple, it's likely that versions of this pkg probably
        # use similar deps- so we're forcing those packages that were
        # accessed for atom matching to remain in memory.
        # end result is less going to disk

        if pkg.live:
            # vcs ebuild that better not be visible
            self.check_visibility_vcs(pkg, reporter)

        today = datetime.today()

        suppressed_depsets = []
        for attr in ("bdepend", "depend", "rdepend", "pdepend"):
            nonexistent = set()
            outdated = set()
            try:
                for orig_node in visit_atoms(pkg, getattr(pkg, attr)):

                    node = strip_atom_use(orig_node)
                    if node not in self.query_cache:
                        if node in self.profiles.global_insoluble:
                            nonexistent.add(node)
                            # insert an empty tuple, so that tight loops further
                            # on don't have to use the slower get method
                            self.query_cache[node] = ()

                        else:
                            matches = caching_iter(
                                self.options.search_repo.itermatch(node))
                            if matches:
                                self.query_cache[node] = matches
                                if orig_node is not node:
                                    self.query_cache[str(orig_node)] = matches
                            elif node.blocks:
                                # check for outdated blockers (2+ years old)
                                if self.existence_repo is not None:
                                    unblocked = atom(str(node).lstrip('!'))
                                    matches = self.existence_repo.match(unblocked)
                                    if matches:
                                        removal = max(
                                            self.existence_repo.removal_date(x) for x in matches)
                                        removal = datetime.strptime(removal, '%Y-%m-%d')
                                        years = round((today - removal).days / 365, 2)
                                        if years > 2:
                                            outdated.add((node, years))
                            else:
                                nonexistent.add(node)
                                self.query_cache[node] = ()
                                self.profiles.global_insoluble.add(node)
                    elif not self.query_cache[node]:
                        nonexistent.add(node)

            except _BlockMemoryExhaustion as e:
                reporter.add_report(UncheckableDep(pkg, attr))
                suppressed_depsets.append(attr)
            if nonexistent:
                reporter.add_report(NonExistentDeps(pkg, attr, nonexistent))
            for node, years in outdated:
                reporter.add_report(
                    OutdatedBlocker(pkg, attr, node, years))

        del nonexistent, outdated

        for attr in ("bdepend", "depend", "rdepend", "pdepend"):
            if attr in suppressed_depsets:
                continue
            depset = getattr(pkg, attr)
            for edepset, profiles in self.depset_cache.collapse_evaluate_depset(
                    pkg, attr, depset):
                self.process_depset(pkg, attr, depset, edepset, profiles, reporter)

    def check_visibility_vcs(self, pkg, reporter):
        for profile in self.profiles:
            if profile.visible(pkg):
                reporter.add_report(VisibleVcsPkg(pkg, profile.key, profile.name))

    def process_depset(self, pkg, attr, depset, edepset, profiles, reporter):
        get_cached_query = self.query_cache.get

        csolutions = []
        for required in edepset.iter_cnf_solutions():
            for node in required:
                if node.blocks:
                    break
            else:
                csolutions.append(required)

        for profile in profiles:
            failures = set()
            # is it visible?  ie, is it masked?
            # if so, skip it.
            # long term, probably should do testing in the same respect we do
            # for other visibility tiers
            cache = profile.cache
            provided = profile.provides_has_match
            insoluble = profile.insoluble
            visible = profile.visible
            for required in csolutions:
                # scan all of the quickies, the caches...
                for node in required:
                    if node in cache:
                        break
                    elif provided(node):
                        break
                else:
                    for node in required:
                        if node in insoluble:
                            pass

                        # get is required since there is an intermix between old style
                        # virtuals and new style- thus the cache priming doesn't get
                        # all of it.
                        src = get_cached_query(strip_atom_use(node), ())
                        if node.use:
                            src = (FakeConfigurable(pkg, profile) for pkg in src)
                            src = (pkg for pkg in src if node.force_True(pkg))
                        if any(True for pkg in src if visible(pkg)):
                            cache.add(node)
                            break
                        else:
                            insoluble.add(node)
                    else:
                        # no matches.  not great, should collect them all
                        failures.update(required)
            if failures:
                reporter.add_report(NonsolvableDeps(
                    pkg, attr, profile.key, profile.name, list(failures)))
