import argparse
import os

from pkgcore.ebuild import repo_objs, repository
from pkgcore.restrictions import packages
from pkgcore.util import commandline
import pytest
from snakeoil.fileutils import write_file
from snakeoil.osutils import pjoin, ensure_dirs

from pkgcheck import addons, base

from .misc import FakePkg, FakeProfile, Options, Tmpdir


class ArgparseCheck(object):

    def process_check(self, args, preset_values={},
                      namespace=None, addon_kls=None, **settings):
        addon_kls = addon_kls if addon_kls is not None else self.addon_kls
        p = commandline.ArgumentParser(domain=False, color=False)
        p.plugin = p.add_argument_group('plugin options')
        addon_kls.mangle_argparser(p)
        args, unknown_args = p.parse_known_args(args, namespace)
        assert unknown_args == []
        orig_out, orig_err = None, None
        for attr, val in preset_values.items():
            setattr(args, attr, val)
        addon_kls.check_args(p, args)
        for attr, val in settings.items():
            assert getattr(args, attr) == val, (
                f"for args {args!r}, {attr} must be {val!r}, got {getattr(args, attr)!r}")
        return args


class TestArchesAddon(ArgparseCheck):

    addon_kls = addons.ArchesAddon

    def test_opts(self):
        for arg in ('-a', '--arches'):
            self.process_check([arg, 'x86'], arches=('x86',))
            self.process_check([arg, 'x86,ppc'], arches=('ppc', 'x86'))
            self.process_check([arg, 'x86,ppc,-x86'], arches=('ppc',))

    def test_default(self):
        self.process_check([], arches=())


class Test_profile_data(object):

    def assertResults(self, profile, known_flags, required_immutable,
                      required_forced, cpv="dev-util/diffball-0.1",
                      key_override=None, data_override=None):
        if key_override is None:
            key = profile.key
        profile_data = addons.ProfileData(
            "test-profile", key_override,
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


class ProfilesMixin(ArgparseCheck, Tmpdir):

    addon_kls = addons.ProfileAddon

    def mk_profiles(self, profiles, base='profiles', arches=None, make_defaults=None):
        os.mkdir(pjoin(self.dir, 'metadata'))
        # write empty masters to suppress warnings
        write_file(pjoin(self.dir, 'metadata', 'layout.conf'), 'w', 'masters=')

        loc = pjoin(self.dir, base)
        os.mkdir(loc)
        if base != 'profiles':
            # write empty masters to suppress warnings
            os.mkdir(pjoin(loc, 'metadata'))
            write_file(pjoin(loc, 'metadata', 'layout.conf'), 'w', 'masters=')
        for profile in profiles:
            assert ensure_dirs(pjoin(loc, profile)), f"failed creating profile {profile!r}"
        if arches is None:
            arches = {val[0] for val in profiles.values()}
        write_file(pjoin(loc, 'arch.list'), 'w', "\n".join(arches))
        write_file(pjoin(loc, 'repo_name'), 'w', 'testing')
        write_file(pjoin(loc, 'eapi'), 'w', '5')
        with open(pjoin(loc, 'profiles.desc'), 'w') as fd:
            for profile, vals in profiles.items():
                l = len(vals)
                if l == 1 or not vals[1]:
                    fd.write(f"{vals[0]}\t{profile}\tstable\n")
                else:
                    fd.write(f"{vals[0]}\t{profile}\t{vals[1]}\n")
                if l == 3 and vals[2]:
                    with open(pjoin(loc, profile, 'deprecated'), 'w') as f:
                        f.write("foon\n#dar\n")
                with open(pjoin(loc, profile, 'make.defaults'), 'w') as f:
                    if make_defaults is not None:
                        f.write('\n'.join(make_defaults))
                    else:
                        f.write(f'ARCH={vals[0]}\n')
                with open(pjoin(loc, profile, 'eapi'), 'w') as f:
                    f.write('5')

    def process_check(self, profiles_base, *args, **kwds):
        namespace = argparse.Namespace()
        if profiles_base is None:
            repo_config = repo_objs.RepoConfig(location=self.dir)
        else:
            repo_config = repo_objs.RepoConfig(location=profiles_base, profiles_base='.')
        namespace.target_repo = repository.UnconfiguredTree(
            repo_config.location, repo_config=repo_config)
        namespace.search_repo = Options()
        namespace.profile_cache = False
        options = ArgparseCheck.process_check(self, namespace=namespace, *args, **kwds)
        return options


class TestProfileAddon(ProfilesMixin):

    def assertProfiles(self, check, key, *profile_names):
        assert (
            sorted(x.name for y in check.profile_evaluate_dict[key] for x in y) ==
            sorted(profile_names))

    def test_defaults(self):
        self.mk_profiles({
            "profile1": ["x86"],
            "profile1/2": ["x86"]},
            base='profiles')
        options = self.process_check(None, [], profiles=None)
        # override the default
        check = self.addon_kls(options)
        assert sorted(check.official_arches) == ['x86']
        assert sorted(check.desired_arches) == ['x86']
        assert sorted(check.profile_evaluate_dict) == ['x86', '~x86']
        self.assertProfiles(check, 'x86', 'profile1', 'profile1/2')

    def test_fallback_defaults(self):
        self.mk_profiles({
            "default-linux/dep": ["x86", False, True],
            "default-linux/dev": ["x86", "dev"],
            "default-linux/exp": ["x86", "exp"],
            "default-linux": ["x86"]},
            base='foo')
        options = self.process_check(pjoin(self.dir, 'foo'), ['--profiles=stable,-stable'])
        check = self.addon_kls(options)
        self.assertProfiles(check, 'x86', 'default-linux', 'default-linux/dev', 'default-linux/exp')

    def test_profiles_base(self):
        self.mk_profiles({
            "default-linux/dep": ["x86", False, True],
            "default-linux": ["x86", "dev"],
            "default-linux/x86": ["x86"]},
            base='foo')
        options = self.process_check(pjoin(self.dir, 'foo'), [])
        check = self.addon_kls(options)
        self.assertProfiles(check, 'x86', 'default-linux', 'default-linux/x86')

    def test_nonexistent(self, capsys):
        self.mk_profiles({
            "x86": ["x86"]},
            base='foo')
        for profiles in ('bar', '-bar', 'x86,bar', 'bar,x86', 'x86,-bar'):
            with pytest.raises(SystemExit) as excinfo:
                options = self.process_check(pjoin(self.dir, 'foo'), [f'--profiles={profiles}'])
            assert excinfo.value.code == 2
            out, err = capsys.readouterr()
            assert not out
            assert "nonexistent profile: 'bar'" in err

    def test_make_defaults(self):
        self.mk_profiles({
            "amd64": ["amd64"],
            "prefix/amd64": ["amd64-linux"]},
            base='foo',
            make_defaults=['ARCH="amd64"'])
        options = self.process_check(pjoin(self.dir, 'foo'), [f'--profiles=prefix/amd64'])
        check = self.addon_kls(options)
        self.assertProfiles(check, 'amd64', 'prefix/amd64')

    def test_make_defaults_missing_arch(self, capsys):
        self.mk_profiles({
            "arch/amd64": ["amd64"]},
            base='foo',
            make_defaults=[])
        with pytest.raises(SystemExit) as excinfo:
            options = self.process_check(pjoin(self.dir, 'foo'), [f'--profiles=arch/amd64'])
        assert excinfo.value.code == 2
        out, err = capsys.readouterr()
        assert not out
        assert "profile make.defaults lacks ARCH setting: 'arch/amd64'" in err

    def test_enable_stable(self):
        self.mk_profiles({
            "default-linux/dep": ["x86", False, True],
            "default-linux/dev": ["x86", "dev"],
            "default-linux/exp": ["x86", "exp"],
            "default-linux": ["x86"]},
            base='foo')
        options = self.process_check(pjoin(self.dir, 'foo'), ['--profiles=stable'])
        check = self.addon_kls(options)
        self.assertProfiles(check, 'x86', 'default-linux')

    def test_disable_stable(self):
        self.mk_profiles({
            "default-linux/dep": ["x86", False, True],
            "default-linux/dev": ["x86", "dev"],
            "default-linux/exp": ["x86", "exp"],
            "default-linux": ["x86"]},
            base='foo')
        options = self.process_check(pjoin(self.dir, 'foo'), ['--profiles=-stable'])
        check = self.addon_kls(options)
        self.assertProfiles(check, 'x86', 'default-linux/dev', 'default-linux/exp')

    def test_enable_dev(self):
        self.mk_profiles({
            "default-linux/dep": ["x86", False, True],
            "default-linux/dev": ["x86", "dev"],
            "default-linux/x86": ["x86"]},
            base='foo')
        options = self.process_check(pjoin(self.dir, 'foo'), ['--profiles=dev'])
        check = self.addon_kls(options)
        self.assertProfiles(check, 'x86', 'default-linux/dev')

    def test_disable_dev(self):
        self.mk_profiles({
            "default-linux/dep": ["x86", False, True],
            "default-linux/dev": ["x86", "dev"],
            "default-linux/x86": ["x86"]},
            base='foo')
        options = self.process_check(pjoin(self.dir, 'foo'), ['--profiles=-dev'])
        check = self.addon_kls(options)
        self.assertProfiles(check, 'x86', 'default-linux/x86')

    def test_enable_exp(self):
        self.mk_profiles({
            "default-linux/dep": ["x86", False, True],
            "default-linux/exp": ["x86", "exp"],
            "default-linux/x86": ["x86"]},
            base='foo')
        options = self.process_check(pjoin(self.dir, 'foo'), ['--profiles=exp'])
        check = self.addon_kls(options)
        self.assertProfiles(check, 'x86', 'default-linux/exp')

    def test_disable_exp(self):
        self.mk_profiles({
            "default-linux/dep": ["x86", False, True],
            "default-linux/exp": ["x86", "exp"],
            "default-linux/x86": ["x86"]},
            base='foo')
        options = self.process_check(pjoin(self.dir, 'foo'), ['--profiles=-exp'])
        check = self.addon_kls(options)
        self.assertProfiles(check, 'x86', 'default-linux/x86')

    def test_enable_deprecated(self):
        self.mk_profiles({
            "default-linux/dep": ["x86", False, True],
            "default-linux/x86": ["x86"]},
            base='foo')
        options = self.process_check(
            pjoin(self.dir, 'foo'), ['--profiles=deprecated'])
        check = self.addon_kls(options)
        self.assertProfiles(check, 'x86', 'default-linux/dep')

    def test_disable_deprecated(self):
        self.mk_profiles({
            "default-linux/dep": ["x86", False, True],
            "default-linux/x86": ["x86"]},
            base='foo')
        options = self.process_check(
            pjoin(self.dir, 'foo'), ['--profiles=-deprecated'])
        check = self.addon_kls(options)
        self.assertProfiles(check, 'x86', 'default-linux/x86')

    def test_profile_enable(self):
        self.mk_profiles({
            "default-linux/dep": ["x86", False, True],
            "default-linux": ["x86"],
            "default-linux/x86": ["x86"]},
            base='foo')
        options = self.process_check(pjoin(self.dir, 'foo'), ['--profiles', 'default-linux/x86'])
        check = self.addon_kls(options)
        self.assertProfiles(check, 'x86', 'default-linux/x86')

    def test_profile_disable(self):
        self.mk_profiles({
            "default-linux/dep": ["x86", False, True],
            "default-linux": ["x86"],
            "default-linux/x86": ["x86"]},
            base='foo')
        options = self.process_check(pjoin(self.dir, 'foo'), ['--profiles=-default-linux/x86'])
        check = self.addon_kls(options)
        self.assertProfiles(check, 'x86', 'default-linux')

    def test_profile_collapsing(self):
        self.mk_profiles({
            'default-linux': ['x86'],
            'default-linux/x86': ["x86"],
            'default-linux/ppc': ['ppc']},
            base='foo')
        options = self.process_check(pjoin(self.dir, 'foo'), [])
        check = self.addon_kls(options)

        # assert they're collapsed properly.
        self.assertProfiles(check, 'x86', 'default-linux', 'default-linux/x86')
        assert len(check.profile_evaluate_dict['x86']) == 1
        assert len(check.profile_evaluate_dict['x86'][0]) == 2
        self.assertProfiles(check, 'ppc', 'default-linux/ppc')

        l = check.identify_profiles(FakePkg("d-b/ab-1", data={'KEYWORDS': 'x86'}))
        assert len(l) == 2, f"checking for profile collapsing: {l!r}"
        assert len(l[0]) == 2, f"checking for proper # of profiles: {l[0]!r}"
        assert sorted(x.name for x in l[0]) == sorted(['default-linux', 'default-linux/x86'])

        # check arch vs ~arch runs (i.e. arch KEYWORDS should also trigger ~arch runs)
        l = check.identify_profiles(FakePkg("d-b/ab-1", data={'KEYWORDS': '~x86'}))
        assert len(l) == 1, f"checking for profile collapsing: {l!r}"
        assert len(l[0]) == 2, f"checking for proper # of profiles: {l[0]!r}"
        assert sorted(x.name for x in l[0]) == sorted(['default-linux', 'default-linux/x86'])

        # check keyword collapsing
        l = check.identify_profiles(FakePkg("d-b/ab-2", data={'KEYWORDS': 'ppc'}))
        assert len(l) == 2, f"checking for profile collapsing: {l!r}"
        assert len(l[0]) == 1, f"checking for proper # of profiles: {l[0]!r}"
        assert l[0][0].name == 'default-linux/ppc'

        l = check.identify_profiles(FakePkg("d-b/ab-2", data={'KEYWORDS': 'foon'}))
        assert len(l) == 0, f"checking for profile collapsing: {l!r}"


class TestUseAddon(ArgparseCheck, Tmpdir):

    addon_kls = addons.UseAddon

    def test_it(self):
        pass
    test_it.skip = "todo"
