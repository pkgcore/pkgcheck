import random

from pkgcheck.checks import deprecated

from .. import misc


def mk_pkg(ver):
    return misc.FakePkg(f"dev-util/diffball-{ver}")


class TestDeprecatedEclass(misc.ReportTestCase):

    check_kls = deprecated.DeprecatedEclassReport
    check = deprecated.DeprecatedEclassReport(None, None)

    def test_no_eclasses(self):
        fake_src = [
            "# This is a fake ebuild\n",
            " # This line contains a leading whitespace\n",
            "# That's it for now\n",
        ]
        self.assertNoReport(self.check, [mk_pkg("0.7.1"), fake_src])

    def test_single_current_eclass(self):
        fake_src = [
            "# This is a fake ebuild\n",
            "EAPI=7\n",
            "\n",
            "inherit git-r3\n",
        ]
        self.assertNoReport(self.check, [mk_pkg("0.7.1"), fake_src])

    def test_deprecated_no_replacement(self):
        eclass = next(
            k for k, v in self.check.blacklist.items() if v == None)

        fake_src = [
            "# This is a fake ebuild\n",
            "EAPI=2\n",
            "\n",
            f"inherit {eclass}\n",
        ]

        r = self.assertReport(self.check, [mk_pkg("0.1"), fake_src])
        assert isinstance(r, deprecated.DeprecatedEclass)
        assert r.eclasses == ((eclass, None),)
        assert f"uses deprecated eclass: [ {eclass} (no replacement) ]" == str(r)

    def test_deprecated_with_replacement(self):
        eclass, replacement = next(
            (k, v) for k, v in self.check.blacklist.items() if v)

        fake_src = [
            "# This is a fake ebuild\n",
            "EAPI=4\n",
            "\n",
            f"inherit {eclass}\n",
        ]

        r = self.assertReport(self.check, [mk_pkg("0.1"), fake_src])
        assert isinstance(r, deprecated.DeprecatedEclass)
        assert r.eclasses == ((eclass, replacement),)
        assert f"uses deprecated eclass: [ {eclass} (migrate to {replacement}) ]" == str(r)

    def test_deprecated_and_current(self):
        eclass, replacement = next(
            (k, v) for k, v in self.check.blacklist.items() if v)

        fake_src = [
            "# This is a fake ebuild\n",
            "EAPI=1\n",
            "\n",
            f"inherit git-r3 {eclass}\n",
        ]

        r = self.assertReport(self.check, [mk_pkg("0.1"), fake_src])
        assert isinstance(r, deprecated.DeprecatedEclass)
        assert r.eclasses == ((eclass, replacement),)
        assert f"uses deprecated eclass: [ {eclass} (migrate to {replacement}) ]" == str(r)

    def test_all_known_deprecated(self):
        fake_src = [
            "# This is a fake ebuild\n",
            "\n",
            f"inherit {' '.join(self.check.blacklist.keys())}\n",
        ]

        r = self.assertReport(self.check, [mk_pkg("0.1"), fake_src])
        assert isinstance(r, deprecated.DeprecatedEclass)
        assert r.eclasses == tuple(sorted(self.check.blacklist.items()))
