#!/usr/bin/env python
#
# Output rst doc for defined pkgcheck keywords.

from __future__ import print_function

from itertools import chain
from textwrap import dedent

from pkgcore.plugin import get_plugins
from snakeoil.sequences import unstable_unique

from pkgcheck import base, plugins


def _rst_header(char, text, newline=True):
    if newline:
        print('\n', end='')
    print(text)
    print(char * len(text))


def main():
    _known_checks = tuple(sorted(
        unstable_unique(get_plugins('check', plugins)),
        key=lambda x: x.__name__))
    _known_keywords = tuple(sorted(
        unstable_unique(chain.from_iterable(
        check.known_results for check in _known_checks)),
        key=lambda x: x.__name__))

    scope_map = {
        base.versioned_feed: base.version_scope,
        base.package_feed: base.package_scope,
        base.category_feed: base.category_scope,
        base.repository_feed: base.repository_scope,
    }

    d = {}
    for keyword in _known_keywords:
        d.setdefault(scope_map[keyword.threshold], set()).add(keyword)

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


if __name__ == '__main__':
    main()
