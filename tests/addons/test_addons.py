import os
from unittest.mock import patch

import pytest
from pkgcheck import addons
from pkgcheck.base import PkgcheckUserException
from pkgcore.restrictions import packages
from snakeoil.osutils import pjoin

from ..misc import FakePkg, FakeProfile, Profile


class TestArchesAddon:

    @pytest.fixture(autouse=True)
    def _setup(self, tool, repo):
        self.tool = tool
        self.repo = repo
        self.args = ['scan', '--repo', repo.location]

    def test_empty_default(self):
        options, _ = self.tool.parse_args(self.args)
        assert options.arches == frozenset()

    def test_repo_default(self):
        with open(pjoin(self.repo.location, 'profiles', 'arch.list'), 'w') as f:
            f.write("arm64\namd64\n")
        options, _ = self.tool.parse_args(self.args)
        assert options.arches == frozenset(['amd64', 'arm64'])

    def test_enabled(self):
        data = (
            ('x86', ['x86']),
            ('ppc', ['ppc']),
            ('x86,ppc', ['ppc', 'x86']),
        )
        for arg, expected in data:
            for opt in ('-a', '--arches'):
                options, _ = self.tool.parse_args(self.args + [f'{opt}={arg}'])
                assert options.arches == frozenset(expected)

    def test_disabled(self):
        # set repo defaults
        with open(pjoin(self.repo.location, 'profiles', 'arch.list'), 'w') as f:
            f.write("arm64\namd64\narm64-linux\n")

        data = (
            ('-x86', ['amd64', 'arm64']),
            ('-x86,-amd64', ['arm64']),
        )
        for arg, expected in data:
            for opt in ('-a', '--arches'):
                options, _ = self.tool.parse_args(self.args + [f'{opt}={arg}'])
                assert options.arches == frozenset(expected)

    def test_unknown(self, capsys):
        # unknown arch checking requires repo defaults
        with open(pjoin(self.repo.location, 'profiles', 'arch.list'), 'w') as f:
            f.write("arm64\namd64\narm64-linux\n")

        for arg in ('foo', 'bar'):
            for opt in ('-a', '--arches'):
                with pytest.raises(SystemExit) as excinfo:
                    self.tool.parse_args(self.args + [f'{opt}={arg}'])
                assert excinfo.value.code == 2
                out, err = capsys.readouterr()
                assert not out
                assert f'unknown arch: {arg}' in err


class TestStableArchesAddon:

    @pytest.fixture(autouse=True)
    def _setup(self, tool, repo):
        self.tool = tool
        self.repo = repo
        self.args = ['scan', '--repo', repo.location]

    def test_empty_default(self):
        options, _ = self.tool.parse_args(self.args)
        assert options.stable_arches == set()

    def test_repo_arches_default(self):
        """Use GLEP 72 arches.desc file if it exists."""
        with open(pjoin(self.repo.location, 'profiles', 'arch.list'), 'w') as f:
            f.write("arm64\namd64\nriscv\n")
        with open(pjoin(self.repo.location, 'profiles', 'arches.desc'), 'w') as f:
            f.write("arm64 stable\namd64 stable\nriscv testing")
        options, _ = self.tool.parse_args(self.args)
        assert options.stable_arches == {'amd64', 'arm64'}

    def test_repo_profiles_default(self):
        """Otherwise arch stability is determined from the profiles.desc file."""
        with open(pjoin(self.repo.location, 'profiles', 'arch.list'), 'w') as f:
            f.write("arm64\namd64\nriscv\n")
        os.mkdir(pjoin(self.repo.location, 'profiles', 'default'))
        with open(pjoin(self.repo.location, 'profiles', 'profiles.desc'), 'w') as f:
            f.write("arm64 default dev\namd64 default stable\nriscv default exp")
        options, _ = self.tool.parse_args(self.args)
        assert options.stable_arches == {'amd64'}

    def test_selected_arches(self):
        for opt in ('-a', '--arches'):
            options, _ = self.tool.parse_args(self.args + [f'{opt}=amd64'])
            assert options.stable_arches == {'amd64'}


class Test_profile_data:

    def assertResults(self, profile, known_flags, required_immutable,
                      required_forced, cpv="dev-util/diffball-0.1",
                      key_override=None, data_override=None):
        profile_data = addons.profiles.ProfileData(
            "test-repo", "test-profile", key_override,
            profile.provides_repo,
            packages.AlwaysFalse, profile.iuse_effective,
            profile.use, profile.pkg_use, profile.masked_use, profile.forced_use, {}, set(),
            'stable', False)
        pkg = FakePkg(cpv, data=data_override)
        immutable, enabled = profile_data.identify_use(pkg, set(known_flags))
        assert immutable == set(required_immutable)
        assert enabled == set(required_forced)

    def test_identify_use(self):
        profile = FakeProfile()
        self.assertResults(profile, [], [], [])

        profile = FakeProfile(masked_use={"dev-util/diffball": ["lib"]})
        self.assertResults(profile, [], [], [])
        self.assertResults(profile, ["lib"], ["lib"], [])

        profile = FakeProfile(masked_use={"=dev-util/diffball-0.2": ["lib"]})
        self.assertResults(profile, ["lib"], [], [])

        profile = FakeProfile(masked_use={"dev-util/foon": ["lib"]})
        self.assertResults(profile, ["lib"], [], [])

        profile = FakeProfile(forced_use={"dev-util/diffball": ["lib"]})
        self.assertResults(profile, [], [], [])
        self.assertResults(profile, ["lib", "bar"], ["lib"], ["lib"])

        profile = FakeProfile(
            forced_use={"dev-util/diffball": ["lib"]},
            masked_use={"dev-util/diffball": ["lib"]})
        self.assertResults(profile, [], [], [])
        # check that masked use wins out over forced.
        self.assertResults(profile, ["lib", "bar"], ["lib"], [])

        profile = FakeProfile(
            forced_use={"dev-util/diffball": ["lib"]},
            masked_use={"dev-util/diffball": ["lib"]})
        self.assertResults(profile, [], [], [])
        # check that masked use wins out over forced.
        self.assertResults(profile, ["lib", "bar"], ["lib"], [])


class TestProfileAddon:

    addon_kls = addons.profiles.ProfileAddon

    @pytest.fixture(autouse=True)
    def _setup(self, tool, repo, tmp_path):
        self.tool = tool
        self.repo = repo
        self.args = ['scan', '--cache-dir', str(tmp_path), '--repo', repo.location]

    def assertProfiles(self, addon, key, *profile_names):
        actual = sorted(x.name for y in addon.profile_evaluate_dict[key] for x in y)
        expected = sorted(profile_names)
        assert actual == expected

    def test_defaults(self):
        profiles = [
            Profile('profile1', 'x86'),
            Profile('profile1/2', 'x86'),
        ]
        self.repo.create_profiles(profiles)
        self.repo.arches.add('x86')
        options, _ = self.tool.parse_args(self.args)
        addon = addons.init_addon(self.addon_kls, options)
        assert sorted(addon.profile_evaluate_dict) == ['x86', '~x86']
        self.assertProfiles(addon, 'x86', 'profile1', 'profile1/2')

    def test_profiles_base(self):
        profiles = [
            Profile('default-linux/dep', 'x86', deprecated=True),
            Profile('default-linux', 'x86', 'dev'),
            Profile('default-linux/x86', 'x86'),
        ]
        self.repo.create_profiles(profiles)
        self.repo.arches.add('x86')
        options, _ = self.tool.parse_args(self.args)
        addon = addons.init_addon(self.addon_kls, options)
        self.assertProfiles(addon, 'x86', 'default-linux', 'default-linux/x86')

    def test_nonexistent(self, capsys):
        profile = Profile('x86', 'x86')
        self.repo.create_profiles([profile])
        for profiles in ('bar', '-bar', 'x86,bar', 'bar,x86', 'x86,-bar'):
            with pytest.raises(SystemExit) as excinfo:
                self.tool.parse_args(self.args + [f'--profiles={profiles}'])
            assert excinfo.value.code == 2
            out, err = capsys.readouterr()
            assert not out
            assert "nonexistent profile: 'bar'" in err

    def test_profiles_args(self):
        profiles = [
            Profile('default-linux/dep', 'x86', deprecated=True),
            Profile('default-linux/dev', 'x86', 'dev'),
            Profile('default-linux/exp', 'x86', 'exp'),
            Profile('default-linux', 'x86'),
        ]
        self.repo.create_profiles(profiles)
        self.repo.arches.add('x86')

        # enable stable
        options, _ = self.tool.parse_args(self.args + ['--profiles=stable'])
        addon = addons.init_addon(self.addon_kls, options)
        self.assertProfiles(addon, 'x86', 'default-linux')

        # disable stable
        options, _ = self.tool.parse_args(self.args + ['--profiles=-stable'])
        addon = addons.init_addon(self.addon_kls, options)
        self.assertProfiles(addon, 'x86', 'default-linux/dev', 'default-linux/exp')

        # enable dev
        options, _ = self.tool.parse_args(self.args + ['--profiles=dev'])
        addon = addons.init_addon(self.addon_kls, options)
        self.assertProfiles(addon, 'x86', 'default-linux/dev')

        # disable dev
        options, _ = self.tool.parse_args(self.args + ['--profiles=-dev'])
        addon = addons.init_addon(self.addon_kls, options)
        self.assertProfiles(addon, 'x86', 'default-linux', 'default-linux/exp')

        # enable exp
        options, _ = self.tool.parse_args(self.args + ['--profiles=exp'])
        addon = addons.init_addon(self.addon_kls, options)
        self.assertProfiles(addon, 'x86', 'default-linux/exp')

        # disable exp
        options, _ = self.tool.parse_args(self.args + ['--profiles=-exp'])
        addon = addons.init_addon(self.addon_kls, options)
        self.assertProfiles(addon, 'x86', 'default-linux', 'default-linux/dev')

        # enable deprecated
        options, _ = self.tool.parse_args(self.args + ['--profiles=deprecated'])
        addon = addons.init_addon(self.addon_kls, options)
        self.assertProfiles(addon, 'x86', 'default-linux/dep')

        # disable deprecated
        options, _ = self.tool.parse_args(self.args + ['--profiles=-deprecated'])
        addon = addons.init_addon(self.addon_kls, options)
        self.assertProfiles(addon, 'x86', 'default-linux', 'default-linux/dev', 'default-linux/exp')

        # enable specific profile
        options, _ = self.tool.parse_args(self.args + ['--profiles', 'default-linux/exp'])
        addon = addons.init_addon(self.addon_kls, options)
        self.assertProfiles(addon, 'x86', 'default-linux/exp')

        # disable specific profile
        options, _ = self.tool.parse_args(self.args + ['--profiles=-default-linux'])
        addon = addons.init_addon(self.addon_kls, options)
        self.assertProfiles(addon, 'x86', 'default-linux/dev', 'default-linux/exp')

    def test_auto_enable_exp_profiles(self):
        profiles = [
            Profile('default-linux/dep', 'x86', deprecated=True),
            Profile('default-linux/dev', 'x86', 'dev'),
            Profile('default-linux/exp', 'x86', 'exp'),
            Profile('default-linux/amd64', 'amd64', 'exp'),
            Profile('default-linux', 'x86'),
        ]
        self.repo.create_profiles(profiles)
        self.repo.arches.update(['amd64', 'x86'])

        # experimental profiles aren't enabled by default
        options, _ = self.tool.parse_args(self.args)
        addon = addons.init_addon(self.addon_kls, options)
        self.assertProfiles(addon, 'x86', 'default-linux', 'default-linux/dev')

        # but are auto-enabled when an arch with only exp profiles is selected
        options, _ = self.tool.parse_args(self.args + ['-a', 'amd64'])
        addon = addons.init_addon(self.addon_kls, options)
        self.assertProfiles(addon, 'amd64', 'default-linux/amd64')

        # or a result keyword is selected that requires them
        options, _ = self.tool.parse_args(self.args + ['-k', 'NonsolvableDepsInExp'])
        addon = addons.init_addon(self.addon_kls, options)
        self.assertProfiles(addon, 'amd64', 'default-linux/amd64')
        self.assertProfiles(addon, 'x86', 'default-linux', 'default-linux/dev', 'default-linux/exp')

    def test_addon_dict(self):
        """ProfileAddon has methods that allow it to act like a dict of profile filters."""
        profiles = [
            Profile('linux/x86', 'x86'),
            Profile('linux/ppc', 'ppc'),
        ]
        self.repo.create_profiles(profiles)
        self.repo.arches.update(['x86', 'ppc'])
        options, _ = self.tool.parse_args(self.args)
        addon = addons.init_addon(self.addon_kls, options)

        assert len(addon) == 4
        assert set(x.name for x in addon) == {'linux/x86', 'linux/ppc'}
        assert len(addon['x86']) == 1
        assert [x.name for x in addon['~x86']] == ['linux/x86']
        assert addon.get('foo', ['foo']) == ['foo']
        assert addon.get('foo') is None

    def test_profile_collapsing(self):
        profiles = [
            Profile('default-linux', 'x86'),
            Profile('default-linux/x86', 'x86'),
            Profile('default-linux/ppc', 'ppc'),
        ]
        self.repo.create_profiles(profiles)
        self.repo.arches.update(['x86', 'ppc'])
        options, _ = self.tool.parse_args(self.args)
        addon = addons.init_addon(self.addon_kls, options)

        # assert they're collapsed properly.
        self.assertProfiles(addon, 'x86', 'default-linux', 'default-linux/x86')
        assert len(addon.profile_evaluate_dict['x86']) == 1
        assert len(addon.profile_evaluate_dict['x86'][0]) == 2
        self.assertProfiles(addon, 'ppc', 'default-linux/ppc')

        groups = addon.identify_profiles(FakePkg("d-b/ab-1", data={'KEYWORDS': 'x86'}))
        assert len(groups) == 2, f"checking for profile collapsing: {groups!r}"
        assert len(groups[0]) == 2, f"checking for proper # of profiles: {groups[0]!r}"
        assert sorted(x.name for x in groups[0]) == sorted(['default-linux', 'default-linux/x86'])

        # check arch vs ~arch runs (i.e. arch KEYWORDS should also trigger ~arch runs)
        groups = addon.identify_profiles(FakePkg("d-b/ab-1", data={'KEYWORDS': '~x86'}))
        assert len(groups) == 1, f"checking for profile collapsing: {groups!r}"
        assert len(groups[0]) == 2, f"checking for proper # of profiles: {groups[0]!r}"
        assert sorted(x.name for x in groups[0]) == sorted(['default-linux', 'default-linux/x86'])

        # check keyword collapsing
        groups = addon.identify_profiles(FakePkg("d-b/ab-2", data={'KEYWORDS': 'ppc'}))
        assert len(groups) == 2, f"checking for profile collapsing: {groups!r}"
        assert len(groups[0]) == 1, f"checking for proper # of profiles: {groups[0]!r}"
        assert groups[0][0].name == 'default-linux/ppc'

        groups = addon.identify_profiles(FakePkg("d-b/ab-2", data={'KEYWORDS': 'foon'}))
        assert len(groups) == 0, f"checking for profile collapsing: {groups!r}"


try:
    import requests
    net_skip = False
except ImportError:
    net_skip = True


@pytest.mark.skipif(net_skip, reason="requests isn't installed")
class TestNetAddon:

    def test_failed_import(self, tool):
        options, _ = tool.parse_args(['scan'])
        addon = addons.NetAddon(options)
        with patch('pkgcheck.addons.net.Session') as net:
            net.side_effect = ImportError('import failed', name='foo')
            with pytest.raises(ImportError):
                addon.session
            # failing to import requests specifically returns a nicer user exception
            net.side_effect = ImportError('import failed', name='requests')
            with pytest.raises(PkgcheckUserException, match='network checks require requests'):
                addon.session

    def test_custom_timeout(self, tool):
        options, _ = tool.parse_args(['scan', '--timeout', '10'])
        addon = addons.NetAddon(options)
        assert isinstance(addon.session, requests.Session)
        assert addon.session.timeout == 10
        # a timeout of zero disables timeouts entirely
        options, _ = tool.parse_args(['scan', '--timeout', '0'])
        addon = addons.NetAddon(options)
        assert addon.session.timeout is None

    def test_args(self, tool):
        options, _ = tool.parse_args(
            ['scan', '--timeout', '10', '--tasks', '50', '--user-agent', 'firefox'])
        addon = addons.NetAddon(options)
        with patch('pkgcheck.addons.net.Session') as net:
            addon.session
        net.assert_called_once_with(concurrent=50, timeout=10, user_agent='firefox')
