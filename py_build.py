import sys
from collections import defaultdict
from functools import partial
from contextlib import contextmanager
from pathlib import Path
from textwrap import dedent

from flit_core import buildapi


@contextmanager
def sys_path():
    orig_path = sys.path[:]
    sys.path.insert(0, str(Path.cwd() / "src"))
    try:
        yield
    finally:
        sys.path = orig_path


def write_verinfo(cleanup_files):
    from snakeoil.version import get_git_version

    cleanup_files.append(path := Path.cwd() / "src/pkgcheck/_verinfo.py")
    path.parent.mkdir(parents=True, exist_ok=True)
    print(f"generating version info: {path}")
    path.write_text(f"version_info={get_git_version(Path.cwd())!r}")


def write_const(cleanup_files):
    cleanup_files.append(path := Path.cwd() / "src/pkgcheck/_const.py")
    print(f"writing path constants to {path}")
    with path.open("w") as f:
        path.chmod(0o644)
        f.write(
            dedent(
                """\
                    from os.path import abspath, exists, join
                    import sys
                    INSTALL_PREFIX = abspath(sys.prefix)
                    if not exists(join(INSTALL_PREFIX, 'lib/pkgcore')):
                        INSTALL_PREFIX = abspath(sys.base_prefix)
                    DATA_PATH = join(INSTALL_PREFIX, 'share/pkgcheck')
                """
            )
        )


def write_objects(cleanup_files):
    cleanup_files.append(path := Path.cwd() / "src/pkgcheck/_objects.py")
    print(f"writing objects to {path}")

    class _kls:
        def __init__(self, module):
            self.module = module

        def __repr__(self):
            return self.module

    with sys_path():
        from pkgcheck import objects

    modules = defaultdict(set)
    objs = defaultdict(list)
    for obj in ("KEYWORDS", "CHECKS", "REPORTERS"):
        for name, cls in getattr(objects, obj).items():
            parent, module = cls.__module__.rsplit(".", 1)
            modules[parent].add(module)
            objs[obj].append((name, _kls(f"{module}.{name}")))

    keywords = tuple(objs["KEYWORDS"])
    checks = tuple(objs["CHECKS"])
    reporters = tuple(objs["REPORTERS"])

    with path.open("w") as f:
        path.chmod(0o644)
        for k, v in sorted(modules.items()):
            f.write(f"from {k} import {', '.join(sorted(v))}\n")
        f.write(
            dedent(
                f"""\
                    KEYWORDS = {keywords}
                    CHECKS = {checks}
                    REPORTERS = {reporters}
                """
            )
        )


def write_files(cleanup_files):
    with sys_path():
        from pkgcheck import base, objects
        from pkgcheck.addons import caches

    (dst := Path.cwd() / "data/share/pkgcheck").mkdir(parents=True, exist_ok=True)

    print("Generating available scopes")
    cleanup_files.append(path := dst / "scopes")
    path.write_text("\n".join(base.scopes) + "\n")

    print("Generating available cache types")
    cache_objs = caches.CachedAddon.caches.values()
    cleanup_files.append(path := dst / "caches")
    path.write_text("\n".join(x.type for x in cache_objs) + "\n")

    for obj in ("KEYWORDS", "CHECKS", "REPORTERS"):
        print(f"Generating {obj.lower()} list")
        cleanup_files.append(path := dst / obj.lower())
        path.write_text("\n".join(getattr(objects, obj)) + "\n")


def prepare_pkgcheck(callback, only_version: bool):
    cleanup_files = []
    try:
        write_verinfo(cleanup_files)
        if not only_version:
            write_const(cleanup_files)
            write_objects(cleanup_files)
            write_files(cleanup_files)

        return callback()
    finally:
        for path in cleanup_files:
            try:
                path.unlink()
            except OSError:
                pass


def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    """Builds a wheel, places it in wheel_directory"""
    callback = partial(buildapi.build_wheel, wheel_directory, config_settings, metadata_directory)
    return prepare_pkgcheck(callback, only_version=False)


def build_editable(wheel_directory, config_settings=None, metadata_directory=None):
    """Builds an "editable" wheel, places it in wheel_directory"""
    callback = partial(
        buildapi.build_editable, wheel_directory, config_settings, metadata_directory
    )
    return prepare_pkgcheck(callback, only_version=True)


def build_sdist(sdist_directory, config_settings=True):
    """Builds an sdist, places it in sdist_directory"""
    callback = partial(buildapi.build_sdist, sdist_directory, config_settings)
    return prepare_pkgcheck(callback, only_version=True)
