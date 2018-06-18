#!/usr/bin/env python3

from setuptools import setup

from snakeoil.dist import distutils_extensions as pkgdist
pkgdist_setup, pkgdist_cmds = pkgdist.setup()


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
        ),
    classifiers=[
        'License :: OSI Approved :: BSD License',
        'Programming Language :: Python :: 3.6',
        ],
    )
)
