#!/usr/bin/env python
#
# Output rst doc for defined pkgcheck checks.

from __future__ import print_function

from collections import defaultdict
import sys
from textwrap import dedent

from snakeoil.sequences import unstable_unique

from pkgcheck.scripts.pkgcheck import _known_checks


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

    d = defaultdict(set)
    for check in _known_checks:
        d[check.scope].add(check)

    _rst_header('=', 'Checks', newline=False)

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

            out('\n{}'.format(check.__name__))
            if summary:
                out('\t' + ' '.join(dedent(summary).strip().split('\n')))
                if explanation:
                    out('\n\t' + ' '.join(dedent(explanation).strip().split('\n')))
                out('\n\n\t(known results: %s)' % ', '.join((r.__name__ for r in sorted(check.known_results, key=lambda x: x.__name__))))


if __name__ == '__main__':
    main()
