#!/usr/bin/env python3
#
# Output rst doc for defined pkgcheck reporters.

from operator import attrgetter
import sys
from textwrap import dedent

from pkgcore.plugin import get_plugins
from snakeoil.sequences import unstable_unique

from pkgcheck import plugins


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

    reporters = sorted(unstable_unique(
        get_plugins('reporter', plugins)),
        key=attrgetter('__name__'))

    _rst_header('=', 'Reporters', newline=False)

    for reporter in reporters:
        if reporter.__doc__ is not None:
            try:
                summary, explanation = reporter.__doc__.split('\n', 1)
            except ValueError:
                summary = reporter.__doc__
                explanation = None
        else:
            summary = None

        _rst_header('-', reporter.__name__)
        if summary:
            out('\n' + dedent(summary).strip())
            if explanation:
                explanation = '\n'.join(dedent(explanation).strip().split('\n'))
                out('\n' + explanation)


if __name__ == '__main__':
    main()
