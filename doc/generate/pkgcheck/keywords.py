#!/usr/bin/env python
#
# Output rst doc for defined pkgcheck keywords.

"""
Keywords
========

List of result keywords that can be produced by pkgcheck separated by scope.

Use \`pkgcheck --list-keywords\` to see the list. Note that running in verbose
mode (e.g. \`pkgcheck --list-keywords -v\`) will colorize and sort the output
into scopes.
"""

from __future__ import print_function

from itertools import chain
import sys
from textwrap import dedent

from snakeoil.sequences import unstable_unique

from pkgcheck import base
from pkgcheck.scripts.pkgcheck import _known_keywords


def main(f=sys.stdout):
    def out(s, **kwargs):
        print(s, file=f, **kwargs)

    def _rst_header(char, text, newline=True):
        if newline:
            out('\n', end='')
        out(text)
        out(char * len(text))

    # add module docstring to output doc
    if __doc__ is not None:
        out(__doc__.strip())

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

            out('\n{}'.format(keyword.__name__))
            if summary:
                out('\t' + ' '.join(dedent(summary).strip().split('\n')))
                if explanation:
                    out('\n\t' + ' '.join(dedent(explanation).strip().split('\n')))


if __name__ == '__main__':
    main()
