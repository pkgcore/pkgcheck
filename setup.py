#!/usr/bin/env python

from setuptools import setup

import pkgdist
pkgdist_setup, pkgdist_cmds = pkgdist.setup()


class test(pkgdist.test):
    blacklist = frozenset(['pkgcheck.plugins'])


setup(
    license='BSD',
    author='Brian Harring, Tim Harder',
    author_email='pkgcore-dev@googlegroups.com',
    description='pkgcore-based QA utility',
    url='https://github.com/pkgcore/pkgcheck',
    data_files=list(
        pkgdist.data_mapping('share/zsh/site-functions', 'completion/zsh'),
    ),
    cmdclass=dict(
        test=test,
        build_py=pkgdist.build_py2to3,
        **pkgdist_cmds
    ),
    classifiers=[
        'License :: OSI Approved :: BSD License',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
    ],
    **pkgdist_setup
)
