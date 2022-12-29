#!/usr/bin/env python3
#
# Output rst doc for defined pkgcheck reporters.

import sys
from textwrap import dedent

from pkgcheck import objects


def main(f=sys.stdout, **kwargs):
    def out(s, **kwargs):
        print(s, file=f, **kwargs)

    def _rst_header(char, text, newline=True, leading=False):
        if newline:
            out("\n", end="")
        if leading:
            out(char * len(text))
        out(text)
        out(char * len(text))

    # add module docstring to output doc
    if __doc__ is not None:
        out(__doc__.strip())

    _rst_header("=", "Reporters", newline=False)

    for reporter in objects.REPORTERS.values():
        if reporter.__doc__ is not None:
            try:
                summary, explanation = reporter.__doc__.split("\n", 1)
            except ValueError:
                summary = reporter.__doc__
                explanation = None
        else:
            summary = None

        _rst_header("-", reporter.__name__, leading=True)
        if summary:
            out("\n" + dedent(summary).strip())
            if explanation:
                explanation = "\n".join(dedent(explanation).strip().split("\n"))
                out("\n" + explanation)


if __name__ == "__main__":
    main()
