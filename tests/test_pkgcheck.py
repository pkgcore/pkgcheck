from pkgcore.test.scripts import helpers

from pkgcheck.scripts import pkgcheck


class TestCommandline(helpers.ArgParseMixin):

    _argparser = pkgcheck.scan

    def test_parser(self):
        self.assertError(
            "argument -r/--repo: couldn't find repo 'spork'",
            '-r', 'spork')
