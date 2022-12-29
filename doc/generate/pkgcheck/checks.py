#!/usr/bin/env python3
#
# Output rst doc for defined pkgcheck checks.

"""
Checks
======

List of checks that can be selected to run.

By default, all checks that operate at the current scope or below will be run.
In other words, if running inside a package directory in a repo, only checks
that operate at a package or version scope will be run. On the other hand, when
running against an entire repo, all defined checks will be run.
"""

import sys
from operator import attrgetter
from textwrap import TextWrapper, dedent

from snakeoil.strings import pluralism as _pl

from pkgcheck import base, objects
from pkgcheck.checks import GentooRepoCheck


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

    wrapper = TextWrapper(width=85)

    for scope in base.scopes.values():
        _rst_header("-", scope.desc.capitalize() + " scope", leading=True)

        checks = (x for x in objects.CHECKS.values() if x.scope == scope)
        for check in checks:
            if check.__doc__ is not None:
                try:
                    summary, explanation = check.__doc__.split("\n", 1)
                except ValueError:
                    summary = check.__doc__
                    explanation = None
            else:
                summary = None

            _rst_header("-", check.__name__)
            if summary:
                out("\n" + dedent(summary).strip())
                if explanation:
                    explanation = "\n".join(dedent(explanation).strip().split("\n"))
                    out("\n" + explanation)
                if issubclass(check, GentooRepoCheck):
                    out("\n\n- Gentoo repo specific")
                known_results = ", ".join(
                    f"`{r.__name__}`_"
                    for r in sorted(check.known_results, key=attrgetter("__name__"))
                )
                out(
                    "\n"
                    + "\n".join(
                        wrapper.wrap(f"(known result{_pl(check.known_results)}: {known_results})")
                    )
                )


if __name__ == "__main__":
    main()
