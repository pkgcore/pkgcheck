#!/usr/bin/env python3
#
# Output rst doc for defined pkgcheck keywords.

"""
Keywords
========

List of result keywords that can be produced by pkgcheck.
"""

import sys
from textwrap import dedent

from pkgcheck import base
from pkgcheck.scripts.pkgcheck import _known_keywords


def main(f=sys.stdout, **kwargs):
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

    for scope in base.known_scopes.values():
        _rst_header('-', scope.desc.capitalize() + ' scope')

        keywords = (x for x in _known_keywords if x.threshold == scope.threshold)
        for keyword in keywords:
            if keyword.__doc__ is not None:
                try:
                    summary, explanation = keyword.__doc__.split('\n', 1)
                except ValueError:
                    summary = keyword.__doc__
                    explanation = None
            else:
                summary = None

            _rst_header('^', keyword.__name__)
            if summary:
                out('\n' + ' '.join(dedent(summary).strip().split('\n')))
                if explanation:
                    out('\n' + ' '.join(dedent(explanation).strip().split('\n')))


if __name__ == '__main__':
    main()
