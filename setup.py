#!/usr/bin/env python

from setuptools import setup

import pkgdist
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
        test=pkgdist.test,
        build_py=pkgdist.build_py2to3,
        ),
    classifiers=[
        'License :: OSI Approved :: BSD License',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        ],
    )
)
