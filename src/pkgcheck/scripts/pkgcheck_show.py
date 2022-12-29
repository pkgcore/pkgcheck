import textwrap
from collections import defaultdict
from operator import attrgetter

from snakeoil.cli import arghparse
from snakeoil.formatters import decorate_forced_wrapping

from .. import base, objects
from ..addons.caches import CachedAddon

show = arghparse.ArgumentParser(prog="pkgcheck show", description="show various pkgcheck info")
list_options = show.add_argument_group("list options")
output_types = list_options.add_mutually_exclusive_group()
output_types.add_argument(
    "-k",
    "--keywords",
    action="store_true",
    default=False,
    help="show available warning/error keywords",
    docs="""
        List all available keywords.

        Use -v/--verbose to show keywords sorted into the scope they run at
        (repository, category, package, or version) along with their
        descriptions.
    """,
)
output_types.add_argument(
    "-c",
    "--checks",
    action="store_true",
    default=False,
    help="show available checks",
    docs="""
        List all available checks.

        Use -v/--verbose to show descriptions and possible keyword results for
        each check.
    """,
)
output_types.add_argument(
    "-s",
    "--scopes",
    action="store_true",
    default=False,
    help="show available keyword/check scopes",
    docs="""
        List all available keyword and check scopes.

        Use -v/--verbose to show scope descriptions.
    """,
)
output_types.add_argument(
    "-r",
    "--reporters",
    action="store_true",
    default=False,
    help="show available reporters",
    docs="""
        List all available reporters.

        Use -v/--verbose to show reporter descriptions.
    """,
)
output_types.add_argument(
    "-C",
    "--caches",
    action="store_true",
    default=False,
    help="show available caches",
    docs="""
        List all available cache types.

        Use -v/--verbose to show more cache information.
    """,
)


def dump_docstring(out, obj, prefix=None):
    if prefix is not None:
        out.first_prefix.append(prefix)
        out.later_prefix.append(prefix)
    try:
        if obj.__doc__ is None:
            raise ValueError(f"no docs for {obj!r}")

        # Docstrings start with an unindented line, everything else is
        # consistently indented.
        lines = obj.__doc__.split("\n")
        # some docstrings start on the second line
        if firstline := lines[0].strip():
            out.write(firstline)
        if len(lines) > 1:
            for line in textwrap.dedent("\n".join(lines[1:])).split("\n"):
                out.write(line)
        else:
            out.write()
    finally:
        if prefix is not None:
            out.first_prefix.pop()
            out.later_prefix.pop()


@decorate_forced_wrapping()
def display_keywords(out, options):
    if options.verbosity < 1:
        out.write("\n".join(sorted(objects.KEYWORDS)), wrap=False)
    else:
        scopes = defaultdict(set)
        for keyword in objects.KEYWORDS.values():
            scopes[keyword.scope].add(keyword)

        for scope in reversed(sorted(scopes)):
            out.write(out.bold, f"{scope.desc.capitalize()} scope:")
            out.write()
            keywords = sorted(scopes[scope], key=attrgetter("__name__"))

            try:
                out.first_prefix.append("  ")
                out.later_prefix.append("  ")
                for keyword in keywords:
                    out.write(out.fg(keyword.color), keyword.__name__, out.reset, ":")
                    dump_docstring(out, keyword, prefix="  ")
            finally:
                out.first_prefix.pop()
                out.later_prefix.pop()


@decorate_forced_wrapping()
def display_checks(out, options):
    if options.verbosity < 1:
        out.write("\n".join(sorted(objects.CHECKS)), wrap=False)
    else:
        d = defaultdict(list)
        for x in objects.CHECKS.values():
            d[x.__module__].append(x)

        for module_name in sorted(d):
            out.write(out.bold, f"{module_name}:")
            out.write()
            checks = d[module_name]
            checks.sort(key=attrgetter("__name__"))

            try:
                out.first_prefix.append("  ")
                out.later_prefix.append("  ")
                for check in checks:
                    out.write(out.fg("yellow"), check.__name__, out.reset, ":")
                    dump_docstring(out, check, prefix="  ")

                    # output result types that each check can generate
                    keywords = []
                    for r in sorted(check.known_results, key=attrgetter("__name__")):
                        keywords.extend([out.fg(r.color), r.__name__, out.reset, ", "])
                    keywords.pop()
                    out.write(*(["  (known results: "] + keywords + [")"]))
                    out.write()

            finally:
                out.first_prefix.pop()
                out.later_prefix.pop()


@decorate_forced_wrapping()
def display_reporters(out, options):
    if options.verbosity < 1:
        out.write("\n".join(sorted(objects.REPORTERS)), wrap=False)
    else:
        out.write("reporters:")
        out.write()
        out.first_prefix.append("  ")
        out.later_prefix.append("  ")
        for reporter in sorted(objects.REPORTERS.values(), key=attrgetter("__name__")):
            out.write(out.bold, out.fg("yellow"), reporter.__name__)
            dump_docstring(out, reporter, prefix="  ")


@show.bind_main_func
def _show(options, out, err):
    if options.checks:
        display_checks(out, options)
    elif options.scopes:
        if options.verbosity < 1:
            out.write("\n".join(base.scopes))
        else:
            for name, scope in base.scopes.items():
                out.write(f"{name} -- {scope.desc} scope")
    elif options.reporters:
        display_reporters(out, options)
    elif options.caches:
        if options.verbosity < 1:
            caches = sorted(map(attrgetter("type"), CachedAddon.caches.values()))
            out.write("\n".join(caches))
        else:
            for cache in sorted(CachedAddon.caches.values(), key=attrgetter("type")):
                out.write(f"{cache.type} -- file: {cache.file}, version: {cache.version}")
    else:
        # default to showing keywords if no output option is selected
        display_keywords(out, options)

    return 0
