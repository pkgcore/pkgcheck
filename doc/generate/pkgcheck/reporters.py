#!/usr/bin/env python
#
# Output rst doc for defined pkgcheck reporters.

from __future__ import print_function

from textwrap import dedent

from pkgcore.plugin import get_plugins
from snakeoil.sequences import unstable_unique

from pkgcheck import plugins


def _rst_header(char, text, newline=True):
    if newline:
        print('\n', end='')
    print(text)
    print(char * len(text))


def main():
    reporters = sorted(unstable_unique(
        get_plugins('reporter', plugins)),
        key=lambda x: x.__name__)

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

        print('\n{}'.format(reporter.__name__))
        if summary:
            print('\t' + ' '.join(dedent(summary).strip().split('\n')))
            if explanation:
                print('\n\t' + '\n\t'.join(dedent(explanation).strip().split('\n')))


if __name__ == '__main__':
    main()
