#!/usr/bin/env python3
#
# Output rst doc for defined pkgcheck keywords.

"""
Keywords
========

List of result keywords that can be produced by pkgcheck.
"""

from collections import defaultdict
import sys
from textwrap import dedent

from snakeoil.strings import pluralism as _pl

from pkgcheck import base, const


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

    related_checks = defaultdict(set)
    for check in const.CHECKS.values():
        for keyword in check.known_results:
            related_checks[keyword].add(check.__name__)

    for scope in base.scopes.values():
        _rst_header('-', scope.desc.capitalize() + ' scope')

        keywords = (x for x in const.KEYWORDS.values() if x.scope == scope)
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
                out('\n' + dedent(summary).strip())
                if explanation:
                    explanation = '\n'.join(dedent(explanation).strip().split('\n'))
                    out('\n' + explanation)
                checks = ', '.join(
                    f'`{c}`_' for c in sorted(related_checks[keyword]))
                out('\n' + f'- level: {keyword.level}')
                out(f'- related check{_pl(related_checks[keyword])}: {checks}')


if __name__ == '__main__':
    main()
