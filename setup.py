#!/usr/bin/env python
# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: BSD/GPL2

import io
import os

from setuptools import setup, find_packages

from pkgcheck import __version__
import pkgdist


class test(pkgdist.test):

    blacklist = frozenset(['pkgcheck.plugins'])

with io.open('README.rst', encoding='utf-8') as f:
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
    packages=find_packages(),
    setup_requires=['snakeoil>=0.6.5'],
    install_requires=[
        'snakeoil>=0.6.5',
        'pkgcore>=0.9.2',
    ],
    scripts=os.listdir('bin'),
    cmdclass={
        "sdist": pkgdist.sdist,
        "test": test,
        "build_py": pkgdist.build_py,
        'build_scripts': pkgdist.build_scripts,
    },
    classifiers=[
        'License :: OSI Approved :: BSD License',
        'License :: OSI Approved :: GNU General Public License v2 (GPLv2)',
        'Programming Language :: Python :: 2.7',
    ],
)
