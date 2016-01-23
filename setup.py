#!/usr/bin/env python
# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: BSD/GPL2

import io
import os

from setuptools import setup, find_packages

import pkgdist


class test(pkgdist.test):

    blacklist = frozenset(['pkgcheck.plugins'])

with io.open('README.rst', encoding='utf-8') as f:
    readme = f.read()

setup(
    name="pkgcheck",
    version=pkgdist.version(),
    license="BSD/GPL2",
    author="Brian Harring, Tim Harder",
    author_email="pkgcore-dev@googlegroups.com",
    description="pkgcore-based QA utility",
    long_description=readme,
    url='https://github.com/pkgcore/pkgcheck',
    packages=find_packages(),
    setup_requires=['snakeoil>=0.6.6'],
    install_requires=[
        'snakeoil>=0.6.6',
        'pkgcore>=0.9.3',
    ],
    scripts=os.listdir('bin'),
    cmdclass={
        "sdist": pkgdist.sdist,
        "test": test,
        "build_py": pkgdist.build_py,
        "build_man": pkgdist.build_man,
        'build_scripts': pkgdist.build_scripts,
    },
    classifiers=[
        'License :: OSI Approved :: BSD License',
        'License :: OSI Approved :: GNU General Public License v2 (GPLv2)',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3.3',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
    ],
)
