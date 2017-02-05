#!/usr/bin/env python
#
# Output rst doc for defined pkgcheck checks.

from collections import defaultdict
from textwrap import dedent

from pkgcore.plugin import get_plugins
from snakeoil.sequences import unstable_unique

from pkgcheck import plugins


def _rst_header(char, text):
    print('\n' + text)
    print(char * len(text))


checks = sorted(unstable_unique(
    get_plugins('check', plugins)),
    key=lambda x: x.__name__)

d = defaultdict(set)
for check in checks:
    d[check.scope].add(check)

_rst_header('=', 'Checks')

scopes = ('version', 'package', 'category', 'repository')
for scope in reversed(sorted(d)):
    _rst_header('-', scopes[scope].capitalize() + ' scope')
    checks = sorted(d[scope], key=lambda x: x.__name__)

    for check in checks:
        if check.__doc__ is not None:
            try:
                summary, explanation = check.__doc__.split('\n', 1)
            except ValueError:
                summary = check.__doc__
                explanation = None
        else:
            summary = None

        print('\n{}'.format(check.__name__))
        if summary:
            print('\t' + ' '.join(dedent(summary).strip().split('\n')))
            if explanation:
                print('\n\t' + ' '.join(dedent(explanation).strip().split('\n')))
