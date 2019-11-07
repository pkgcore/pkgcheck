#!/usr/bin/env python3

from collections import defaultdict
from distutils import log
from distutils.command import install_data as dst_install_data
from distutils.util import byte_compile
from itertools import chain
import os
import sys
from textwrap import dedent

from setuptools import setup

from snakeoil.dist import distutils_extensions as pkgdist
pkgdist_setup, pkgdist_cmds = pkgdist.setup()

DATA_INSTALL_OFFSET = 'share/pkgcheck'


class install(pkgdist.install):
    """Install wrapper to generate and install pkgcheck-related files."""

    def run(self):
        pkgdist.install.run(self)
        target = self.install_data
        root = self.root or '/'
        if target.startswith(root):
            target = os.path.join('/', os.path.relpath(target, root))
        target = os.path.abspath(target)

        if not self.dry_run:
            # Install configuration data so the program can find its content,
            # rather than assuming it is running from a tarball/git repo.
            write_obj_lists(self.install_purelib, target)

            # Install module plugincache
            # TODO: move this to pkgdist once plugin support is moved to snakeoil
            with pkgdist.syspath(pkgdist.PACKAGEDIR):
                from pkgcheck import plugins
                from pkgcore import plugin
                log.info('Generating plugin cache')
                path = os.path.join(self.install_purelib, 'pkgcheck', 'plugins')
                plugin.initialize_cache(plugins, force=True, cache_dir=path)


def write_obj_lists(python_base, install_prefix):
    """Generate config file of keyword, check, and other object lists."""
    path = os.path.join(python_base, pkgdist.MODULE_NAME, "_const.py")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    log.info(f'writing config to {path!r}')

    # hack to drop quotes on modules in generated files
    class _kls(object):
        def __init__(self, module):
            self.module = module
        def __repr__(self):
            return self.module

    with pkgdist.syspath(pkgdist.PACKAGEDIR):
        from pkgcheck import const

    modules = defaultdict(set)
    objs = defaultdict(list)
    for obj in ('KEYWORDS', 'CHECKS', 'REPORTERS'):
        for name, cls in getattr(const, obj).items():
            parent, module = cls.__module__.rsplit('.', 1)
            modules[parent].add(module)
            objs[obj].append((name, _kls(f'{module}.{name}')))

    keywords = tuple(objs['KEYWORDS'])
    checks = tuple(objs['CHECKS'])
    reporters = tuple(objs['REPORTERS'])

    with open(path, 'w') as f:
        os.chmod(path, 0o644)
        for k, v in sorted(modules.items()):
            f.write(f"from {k} import {', '.join(sorted(v))}\n")
        f.write(dedent(f"""\
            KEYWORDS = {keywords}
            CHECKS = {checks}
            REPORTERS = {reporters}
        """))

        # write install path constants to config
        if install_prefix != os.path.abspath(sys.prefix):
            # write more dynamic _const file for wheel installs
            f.write(dedent("""\
                import os.path as osp
                import sys
                INSTALL_PREFIX = osp.abspath(sys.prefix)
                DATA_PATH = osp.join(INSTALL_PREFIX, {!r})
            """.format(DATA_INSTALL_OFFSET)))
        else:
            f.write("INSTALL_PREFIX=%r\n" % install_prefix)
            f.write("DATA_PATH=%r\n" %
                    os.path.join(install_prefix, DATA_INSTALL_OFFSET))

    # only optimize during install, skip during wheel builds
    if install_prefix == os.path.abspath(sys.prefix):
        byte_compile([path], prefix=python_base)
        byte_compile([path], optimize=1, prefix=python_base)
        byte_compile([path], optimize=2, prefix=python_base)


class install_data(dst_install_data.install_data):
    """Generate data files for install.

    Currently this includes keyword, check, and reporter name lists.
    """

    def run(self):
        self.__generate_files()
        super().run()

    def __generate_files(self):
        with pkgdist.syspath(pkgdist.PACKAGEDIR):
            from pkgcheck import const

        os.makedirs(os.path.join(pkgdist.REPODIR, '.generated'), exist_ok=True)
        files = []
        for obj in ('KEYWORDS', 'CHECKS', 'REPORTERS'):
            log.info(f'Generating {obj.lower()} list')
            path = os.path.join(pkgdist.REPODIR, '.generated', obj.lower())
            with open(path, 'w') as f:
                f.write('\n'.join(getattr(const, obj).keys()) + '\n')
            files.append(os.path.join('.generated', obj.lower()))
        self.data_files.append(('share/pkgcheck', files))


class test(pkgdist.pytest):
    """Wrapper to enforce testing against built version."""

    def run(self):
        # This is fairly hacky, but is done to ensure that the tests
        # are ran purely from what's in build, reflecting back to the source config data.
        key = 'PKGCHECK_OVERRIDE_REPO_PATH'
        original = os.environ.get(key)
        try:
            os.environ[key] = os.path.dirname(os.path.realpath(__file__))
            super().run()
        finally:
            if original is not None:
                os.environ[key] = original
            else:
                os.environ.pop(key, None)


setup(**dict(pkgdist_setup,
    license='BSD',
    author='Tim Harder',
    author_email='radhermit@gmail.com',
    description='pkgcore-based QA utility',
    url='https://github.com/pkgcore/pkgcheck',
    data_files=list(chain(
        pkgdist.data_mapping('share/zsh/site-functions', 'completion/zsh'),
        pkgdist.data_mapping('share/pkgcheck', 'data'),
        )),
    cmdclass=dict(
        pkgdist_cmds,
        test=test,
        install_data=install_data,
        install=install,
        ),
    classifiers=[
        'License :: OSI Approved :: BSD License',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        ],
    extras_require={
        'network': ['requests'],
        },
    )
)
