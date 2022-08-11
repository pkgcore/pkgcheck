#!/usr/bin/env python3
#
# Output rst doc for defined pkgcheck keywords.

"""
Keywords
========

List of result keywords that can be produced by pkgcheck.
"""

import sys
from collections import defaultdict
from textwrap import dedent

from snakeoil.strings import pluralism as _pl

from pkgcheck import base, objects
from pkgcheck.checks import GentooRepoCheck


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
    for check in objects.CHECKS.values():
        for keyword in check.known_results:
            related_checks[keyword].add(check)

    for scope in base.scopes.values():
        _rst_header('-', scope.desc.capitalize() + ' scope')

        keywords = (x for x in objects.KEYWORDS.values() if x.scope == scope)
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
                if all(issubclass(x, GentooRepoCheck) for x in related_checks[keyword]):
                    out(f'\n- Gentoo repo specific')
                out('\n' + f'- level: {keyword.level}')
                checks = ', '.join(sorted(
                    f'`{c.__name__}`_' for c in related_checks[keyword]))
                out(f'- related check{_pl(related_checks[keyword])}: {checks}')


if __name__ == '__main__':
    main()
