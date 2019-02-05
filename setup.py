#!/usr/bin/env python3

from distutils import log
import os

from setuptools import setup

from snakeoil.dist import distutils_extensions as pkgdist
pkgdist_setup, pkgdist_cmds = pkgdist.setup()


class install(pkgdist.install):
    """Install wrapper to generate and install pkgcheck-related files."""

    def run(self):
        pkgdist.install.run(self)
        if not self.dry_run:
            # Install module plugincache
            # TODO: move this to pkgdist once plugin support is moved to snakeoil
            with pkgdist.syspath(pkgdist.PACKAGEDIR):
                from pkgcheck import plugins
                from pkgcore import plugin
                log.info('Generating plugin cache')
                path = os.path.join(self.install_purelib, 'pkgcheck', 'plugins')
                plugin.initialize_cache(plugins, force=True, cache_dir=path)


setup(**dict(pkgdist_setup,
    license='BSD',
    author='Brian Harring, Tim Harder',
    description='pkgcore-based QA utility',
    url='https://github.com/pkgcore/pkgcheck',
    data_files=list(
        pkgdist.data_mapping('share/zsh/site-functions', 'completion/zsh'),
        ),
    cmdclass=dict(
        pkgdist_cmds,
        test=pkgdist.pytest,
        install=install,
        ),
    classifiers=[
        'License :: OSI Approved :: BSD License',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        ],
    )
)
