#!/usr/bin/env python
# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: BSD/GPL2

import os

from setuptools import setup, find_packages

from pkgcheck import __version__
from pkgdist import distutils_extensions as pkg_dist


class test(pkg_dist.test):

    blacklist = frozenset(['pkgcheck.plugins'])

with open('README.rst', 'r') as f:
    readme = f.read()

setup(
    name="pkgcheck",
    version=__version__,
    license="BSD/GPL2",
    author="Brian Harring, Tim Harder",
    author_email="pkgcore-dev@googlegroups.com",
    description="pkgcore-based QA utility",
    long_description=readme,
    url='https://github.com/pkgcore/pkgcheck',
    packages=find_packages(exclude=['pkgdist']),
    install_requires=[
        'snakeoil>=0.6.4',
        'pkgcore>=0.9.1',
    ],
    scripts=os.listdir('bin'),
    cmdclass={
        "sdist": pkg_dist.sdist,
        "test": test,
        "build_py": pkg_dist.build_py,
        'build_scripts': pkg_dist.build_scripts,
    },
    classifiers=[
        'License :: OSI Approved :: BSD License',
        'License :: OSI Approved :: GNU General Public License v2 (GPLv2)',
        'Programming Language :: Python :: 2.7',
    ],
)
