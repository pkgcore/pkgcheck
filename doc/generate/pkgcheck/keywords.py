#!/usr/bin/env python
#
# Output rst doc for defined pkgcheck keywords.

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

d = {}
for x in checks:
    d.setdefault(x.scope, set()).update(x.known_results)

_rst_header('=', 'Keywords')

scopes = ('version', 'package', 'category', 'repository')
for scope in reversed(sorted(d)):
    _rst_header('-', scopes[scope].capitalize() + ' scope')
    keywords = sorted(d[scope], key=lambda x: x.__name__)

    for keyword in keywords:
        if keyword.__doc__ is not None:
            try:
                summary, explanation = keyword.__doc__.split('\n', 1)
            except ValueError:
                summary = keyword.__doc__
                explanation = None
        else:
            summary = None

        print('\n{}'.format(keyword.__name__))
        if summary:
            print('\t' + ' '.join(dedent(summary).strip().split('\n')))
            if explanation:
                print('\n\t' + ' '.join(dedent(explanation).strip().split('\n')))
