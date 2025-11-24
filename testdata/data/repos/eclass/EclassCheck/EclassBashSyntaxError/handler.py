import copy

# TODO: rip this out and just integrate json registries properly
from pkgcheck.reporters import JsonStream

old_bash_result = list(
    JsonStream.from_iter(
        [
            '{"__class__": "EclassBashSyntaxError", "eclass": "bad", "lineno": "12", "error": "syntax error: unexpected end of file"}'
        ]
    )
)[0]

new_bash_result = copy.deepcopy(old_bash_result)
new_bash_result.error = "syntax error: unexpected end of file from `{' command on line 11"  # pyright: ignore[reportAttributeAccessIssue]


def handler(result) -> bool:
    return result == old_bash_result or result == new_bash_result
