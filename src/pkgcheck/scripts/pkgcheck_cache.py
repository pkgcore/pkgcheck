import os

from snakeoil.cli import arghparse
from snakeoil.osutils import pjoin

from .. import base, const
from ..addons import init_addon
from ..addons.caches import CachedAddon
from .argparse_actions import CacheNegations
from .argparsers import repo_argparser

cache = arghparse.ArgumentParser(
    prog='pkgcheck cache', description='perform cache operations',
    parents=(repo_argparser,),
    docs="""
        Various types of caches are used by pkgcheck. This command supports
        running operations on them including updates and removals.
    """)
cache.add_argument(
    '--cache-dir', type=arghparse.create_dir, default=const.USER_CACHE_DIR,
    help='directory to use for storing cache files')
cache_actions = cache.add_mutually_exclusive_group()
cache_actions.add_argument(
    '-l', '--list', dest='list_cache', action='store_true',
    help='list available caches')
cache_actions.add_argument(
    '-u', '--update', dest='update_cache', action='store_true',
    help='update caches')
cache_actions.add_argument(
    '-R', '--remove', dest='remove_cache', action='store_true',
    help='forcibly remove caches')
cache.add_argument(
    '-f', '--force', dest='force_cache', action='store_true',
    help='forcibly update/remove caches')
cache.add_argument(
    '-n', '--dry-run', action='store_true',
    help='dry run without performing any changes')
cache.add_argument(
    '-t', '--type', dest='cache', action=CacheNegations,
    help='target cache types')


@cache.bind_pre_parse
def _setup_cache_addons(parser, namespace):
    """Load all addons using caches and their argparser changes before parsing."""
    for addon in base.get_addons(CachedAddon.caches):
        addon.mangle_argparser(parser)


@cache.bind_early_parse
def _setup_cache(parser, namespace, args):
    if namespace.target_repo is None:
        namespace.target_repo = namespace.config.get_default('repo')
    return namespace, args


@cache.bind_final_check
def _validate_cache_args(parser, namespace):
    enabled_caches = {k for k, v in namespace.cache.items() if v}
    cache_addons = (
        addon for addon in CachedAddon.caches
        if addon.cache.type in enabled_caches)
    # sort caches by type
    namespace.cache_addons = sorted(cache_addons, key=lambda x: x.cache.type)

    namespace.enabled_caches = enabled_caches


@cache.bind_main_func
def _cache(options, out, err):
    if options.remove_cache:
        cache_obj = CachedAddon(options)
        cache_obj.remove_caches()
    elif options.update_cache:
        for addon_cls in options.pop('cache_addons'):
            init_addon(addon_cls, options)
    else:
        # list existing caches
        cache_obj = CachedAddon(options)
        repos_dir = pjoin(options.cache_dir, 'repos')
        for cache_type in sorted(options.enabled_caches):
            paths = cache_obj.existing_caches[cache_type]
            if paths:
                out.write(out.fg('yellow'), f'{cache_type} caches: ', out.reset)
            for path in paths:
                repo = str(path.parent)[len(repos_dir):]
                # non-path repo ids get path separator stripped
                if repo.count(os.sep) == 1:
                    repo = repo.lstrip(os.sep)
                out.write(repo)

    return 0
