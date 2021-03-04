import os

from pkgcheck.checks import repo_metadata
from pkgcore.ebuild.repository import UnconfiguredTree
from pkgcore.test.misc import FakePkg
from snakeoil.cli import arghparse
from snakeoil.osutils import pjoin

from .. import misc


class TestPackageUpdatesCheck(misc.Tmpdir, misc.ReportTestCase):

    check_kls = repo_metadata.PackageUpdatesCheck

    def mk_check(self, pkgs=(), **kwargs):
        # TODO: switch to using a repo fixture when available
        repo_dir = pjoin(self.dir, misc.random_str())
        os.makedirs(pjoin(repo_dir, 'metadata'))
        with open(pjoin(repo_dir, 'metadata', 'layout.conf'), 'w') as f:
            f.write('masters =\n')

        os.makedirs(pjoin(repo_dir, 'profiles', 'updates'))
        with open(pjoin(repo_dir, 'profiles', 'repo_name'), 'w') as f:
            f.write('fake\n')
        for filename, updates in kwargs.items():
            with open(pjoin(repo_dir, 'profiles', 'updates', filename), 'w') as f:
                f.write('\n'.join(updates))

        for pkg in pkgs:
            pkg = FakePkg(pkg)
            pkg_path = pjoin(
                repo_dir, pkg.category, pkg.package, f'{pkg.package}-{pkg.fullver}.ebuild')
            os.makedirs(os.path.dirname(pkg_path), exist_ok=True)
            with open(pkg_path, 'w') as f:
                f.write('SLOT=0\n')

        repo = UnconfiguredTree(repo_dir)
        options = arghparse.Namespace(target_repo=repo, search_repo=repo)
        return self.check_kls(options)

    def test_no_updates(self):
        # no update files
        self.assertNoReport(self.mk_check(), [])

        # empty file
        updates = {'1Q-2020': []}
        self.assertNoReport(self.mk_check(**updates), [])

    def test_bad_update_filenames(self):
        # only files named using the format [1-4]Q-[YYYY] are allowed
        updates = {'foobar': ['blah']}
        r = self.assertReport(self.mk_check(**updates), [])
        assert isinstance(r, repo_metadata.BadPackageUpdate)
        assert "incorrectly named update file: 'foobar'" in str(r)

        updates = {'5Q-2020': ['blah']}
        r = self.assertReport(self.mk_check(**updates), [])
        assert isinstance(r, repo_metadata.BadPackageUpdate)
        assert "incorrectly named update file: '5Q-2020'" in str(r)

        # hidden files will be flagged
        updates = {'.1Q-2020.swp': ['blah']}
        r = self.assertReport(self.mk_check(**updates), [])
        assert isinstance(r, repo_metadata.BadPackageUpdate)
        assert "incorrectly named update file: '.1Q-2020.swp'" in str(r)

    def test_empty_line(self):
        updates = {'1Q-2020': ['  ']}
        r = self.assertReport(self.mk_check(**updates), [])
        assert isinstance(r, repo_metadata.BadPackageUpdate)
        assert "file '1Q-2020': empty line 1" in str(r)

    def test_extra_whitespace(self):
        pkgs = ('dev-util/foo-0', 'dev-util/bar-1')
        for update in (' move dev-util/foo dev-util/bar',  # prefix
                       'move dev-util/foo dev-util/bar '):  # suffix
            updates = {'1Q-2020': [update]}
            r = self.assertReport(self.mk_check(pkgs=pkgs, **updates), [])
            assert isinstance(r, repo_metadata.BadPackageUpdate)
            assert 'extra whitespace' in str(r)
            assert 'on line 1' in str(r)

    def test_old_pkg_update(self):
        pkgs = ('dev-util/blah-0', 'dev-libs/foon-1')
        for update in ('move dev-util/foo dev-util/bar',  # old pkg move
                       'slotmove dev-util/bar 0 1'):  # old slot move
            updates = {'1Q-2020': [update]}
            r = self.assertReport(self.mk_check(pkgs=pkgs, **updates), [])
            assert isinstance(r, repo_metadata.OldPackageUpdate)
            assert r.pkg == 'dev-util/bar'
            assert "'dev-util/bar' unavailable" in str(r)

    def test_old_multimove_pkg_update(self):
        update = ['move dev-util/foo dev-util/bar', 'move dev-util/bar dev-util/blah']
        pkgs = ('dev-util/blaz-0', 'dev-libs/foon-1')
        updates = {'1Q-2020': update}
        r = self.assertReport(self.mk_check(pkgs=pkgs, **updates), [])
        assert isinstance(r, repo_metadata.OldMultiMovePackageUpdate)
        assert r.pkg == 'dev-util/blah'
        assert r.moves == ('dev-util/foo', 'dev-util/bar', 'dev-util/blah')
        assert "'dev-util/blah' unavailable" in str(r)

    def test_multimove_pkg_update(self):
        update = ['move dev-util/foo dev-util/bar', 'move dev-util/bar dev-util/blah']
        pkgs = ('dev-util/blah-0', 'dev-libs/foon-1')
        updates = {'1Q-2020': update}
        r = self.assertReport(self.mk_check(pkgs=pkgs, **updates), [])
        assert isinstance(r, repo_metadata.MultiMovePackageUpdate)
        assert r.pkg == 'dev-util/foo'
        assert r.moves == ('dev-util/foo', 'dev-util/bar', 'dev-util/blah')
        assert "'dev-util/foo': multi-move update" in str(r)

    def test_move_to_self_pkg_update(self):
        update = ['move dev-util/foo dev-util/foo']
        pkgs = ('dev-util/foo-0',)
        updates = {'1Q-2020': update}
        r = self.assertReport(self.mk_check(pkgs=pkgs, **updates), [])
        assert isinstance(r, repo_metadata.RedundantPackageUpdate)
        assert r.updates == ('move', 'dev-util/foo', 'dev-util/foo')
        assert "update line moves to the same package/slot" in str(r)

    def test_slot_move_to_self_pkg_update(self):
        update = ['slotmove dev-util/foo 0 0']
        pkgs = ('dev-util/foo-0',)
        updates = {'1Q-2020': update}
        r = self.assertReport(self.mk_check(pkgs=pkgs, **updates), [])
        assert isinstance(r, repo_metadata.RedundantPackageUpdate)
        assert r.updates == ('slotmove', 'dev-util/foo', '0', '0')
        assert "update line moves to the same package/slot" in str(r)
