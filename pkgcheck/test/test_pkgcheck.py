# Copyright: 2006 Marien Zwart <marienz@gentoo.org>
# License: BSD/GPL2

from pkgcore.test import TestCase
from pkgcore.test.scripts import helpers

from pkgcheck.scripts import pkgcheck


class CommandlineTest(TestCase, helpers.ArgParseMixin):

    _argparser = pkgcheck.argparser

    def test_parser(self):
        self.assertError(
            'No target repo specified on commandline or suite and current '
            'directory is not inside a known repo.')
        self.assertError(
            "argument -r/--repo: couldn't find repo 'spork'",
            '-r', 'spork')
