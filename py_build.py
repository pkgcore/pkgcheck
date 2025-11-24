import os
import sys
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
        os.fchmod(f.fileno(), 0o644)
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


def get_objects_path():
    return Path.cwd() / "src/pkgcheck/_objects.py"


def wipe_objects_on_disk():
    get_objects_path().unlink(missing_ok=True)


def write_objects(cleanup_files):
    cleanup_files.append(path := get_objects_path())
    print(f"writing objects to {path}")

    with sys_path():
        from pkgcheck import objects

    targets = ["CHECKS", "KEYWORDS", "REPORTERS"]
    with path.open("w") as f:
        os.fchmod(f.fileno(), 0o644)
        modules = set()
        for cls_type in targets:
            modules.update(cls.__module__ for cls in getattr(objects, cls_type).values())
        for module in sorted(modules):
            f.write(f"import {module}\n")

        for cls_type in targets:
            f.write("\n")

            registry = getattr(objects, cls_type)

            f.write(f"{cls_type} = (\n")
            for name, cls in sorted(registry.items(), key=lambda x: x[0]):
                f.write(f"  ({name!r}, {cls.__module__}.{cls.__name__}),\n")
            f.write(")\n")


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
        path.write_text("\n".join(sorted(getattr(objects, obj))) + "\n")


@contextmanager
def create_generated_files():
    # the objects registry isn't hot reloadable, and it's fragile for wiping
    # it if it already loaded the _objects_file.  Thus just shoot it first thing.
    wipe_objects_on_disk()
    cleanup_files = []
    try:
        write_verinfo(cleanup_files)
        write_const(cleanup_files)
        write_objects(cleanup_files)
        write_files(cleanup_files)
        yield
    finally:
        for path in cleanup_files:
            try:
                path.unlink()
            except OSError:
                pass


def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    """Builds a wheel, places it in wheel_directory"""
    with create_generated_files():
        return buildapi.build_wheel(wheel_directory, config_settings, metadata_directory)


build_editable = buildapi.build_editable


def build_sdist(sdist_directory, config_settings=True):
    """Builds an sdist, places it in sdist_directory"""
    with create_generated_files():
        return buildapi.build_sdist(sdist_directory, config_settings)
