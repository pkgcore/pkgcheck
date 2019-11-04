from snakeoil.osutils import pjoin

from pkgcheck import addons, feeds

from .misc import FakePkg
from .test_addons import ArgparseCheck, ProfilesMixin


class TestQueryCacheAddon(ArgparseCheck):

    addon_kls = feeds.QueryCache
    default_reset = 'package'

    def test_opts(self):
        for val in ('version', 'package', 'category'):
            self.process_check(['--reset-caching-per', val], query_caching_freq=val)

    def test_default(self):
        self.process_check([], query_caching_freq=self.default_reset)

    def test_feed(self):
        options = self.process_check([])
        check = self.addon_kls(options)
        assert check.options.query_caching_freq == self.default_reset
        check.query_cache['foo'] = 'bar'
        pkg = FakePkg('dev-util/diffball-0.5')
        check.feed(pkg)
        assert not check.query_cache


class TestEvaluateDepSet(ProfilesMixin):

    addon_kls = feeds.EvaluateDepSet

    def get_check(self, *profiles):
        # Carefully tweak profile addon to get an instance since evaluate
        # relies on it.
        profile_options = self.process_check(
            None, [f"--profiles={','.join(profiles)}"], addon_kls=addons.ProfileAddon)
        profile_addon = addons.ProfileAddon(profile_options)
        return self.addon_kls(profile_options, profile_addon=profile_addon)

    def test_it(self):
        with open(pjoin(self.dir, "arch.list"), "w") as f:
            f.write("\n".join(('amd64', 'ppc', 'x86')))

        self.mk_profiles({
            "1": ["x86"],
            "2": ["x86"],
            "3": ["ppc"]},
            base='profiles')

        with open(pjoin(self.dir, 'profiles', '1', 'package.use.stable.mask'), 'w') as f:
            f.write('dev-util/diffball foo')
        with open(pjoin(self.dir, 'profiles', '2', 'package.use.stable.force'), 'w') as f:
            f.write('=dev-util/diffball-0.1 bar foo')
        with open(pjoin(self.dir, 'profiles', '3', 'package.use.stable.force'), 'w') as f:
            f.write('dev-util/diffball bar foo')

        check = self.get_check('1', '2', '3')

        def get_rets(ver, attr, KEYWORDS="x86", **data):
            data["KEYWORDS"] = KEYWORDS
            pkg = FakePkg(f"dev-util/diffball-{ver}", data=data)
            return check.collapse_evaluate_depset(pkg, attr, getattr(pkg, attr))

        # few notes... for ensuring proper profiles came through, use
        # sorted(x.name for x in blah); reasoning is that it will catch
        # if duplicates come through, *and* ensure proper profile collapsing

        # shouldn't return anything due to no profiles matching the keywords.
        assert get_rets("0.0.1", "depend", KEYWORDS="foon") == []
        l = get_rets("0.0.2", "depend")
        assert len(l) == 1, f"must collapse all profiles down to one run: got {l!r}"
        assert len(l[0][1]) == 4, "must have four runs, (arch and ~arch for each profile)"
        assert sorted(set(x.name for x in l[0][1])) == ['1', '2'], f"must have two profiles: got {l!r}"
        assert l[0][1][0].key == 'x86'
        assert l[0][1][1].key == 'x86'

        l = get_rets(
            "0.1", "rdepend",
            RDEPEND="x? ( dev-util/confcache ) foo? ( dev-util/foo ) "
                    "bar? ( dev-util/bar ) !bar? ( dev-util/nobar ) x11-libs/xserver"
        )

        assert len(l) == 3, f"must collapse all profiles down to 3 runs: got {l!r}"

        # ordering is potentially random; thus pull out which depset result is
        # which based upon profile
        l1 = [x for x in l if x[1][0].name == '1'][0]
        l2 = [x for x in l if x[1][0].name == '2'][0]

        assert (
            set(str(l1[0]).split()) ==
            {'dev-util/confcache', 'dev-util/bar', 'dev-util/nobar', 'x11-libs/xserver'})

        assert (
            set(str(l2[0]).split()) ==
            {'dev-util/confcache', 'dev-util/foo', 'dev-util/bar', 'x11-libs/xserver'})

        # test feed wiping, using an empty depset; if it didn't clear, then
        # results from a pkg/attr tuple from above would come through rather
        # then an empty.
        pkg = FakePkg('dev-util/diffball-0.5')
        check.feed(pkg)
        l = get_rets("0.1", "rdepend")
        assert len(l) == 1, f"feed didn't clear the cache- should be len 1: {l!r}"

        check.feed(pkg)

        # ensure it handles arch right.
        l = get_rets("0", "depend", KEYWORDS="ppc x86")
        assert len(l) == 1, f"should be len 1, got {l!r}"
        assert sorted(set(x.name for x in l[0][1])) == ["1", "2", "3"], (
            f"should have three profiles of 1-3, got {l[0][1]!r}")

        # ensure it's caching profile collapsing, iow, keywords for same ver
        # that's partially cached (single attr at least) should *not* change
        # things.

        l = get_rets("0", "depend", KEYWORDS="ppc")
        assert sorted(set(x.name for x in l[0][1])) == ['1', '2', '3'], (
            f"should have 3 profiles, got {l[0][1]!r}\nthis indicates it's "
            "re-identifying profiles every invocation, which is unwarranted ")

        l = get_rets("1", "depend", KEYWORDS="ppc x86",
            DEPEND="ppc? ( dev-util/ppc ) !ppc? ( dev-util/x86 )")
        assert len(l) == 2, f"should be len 2, got {l!r}"

        # same issue, figure out what is what
        l1 = [x[1] for x in l if str(x[0]).strip() == "dev-util/ppc"][0]
        l2 = [x[1] for x in l if str(x[0]).strip() == "dev-util/x86"][0]

        assert sorted(set(x.name for x in l1)) == ["3"]
        assert sorted(set(x.name for x in l2)) == ["1", "2"]
