#!/usr/bin/env python

import io
import os

from setuptools import setup, find_packages

import pkgdist


class test(pkgdist.test):

    blacklist = frozenset(['pkgcheck.plugins'])

with io.open('README.rst', encoding='utf-8') as f:
    readme = f.read()

setup(
    name=pkgdist.MODULE,
    version=pkgdist.version(),
    license='BSD',
    author='Brian Harring, Tim Harder',
    author_email='pkgcore-dev@googlegroups.com',
    description='pkgcore-based QA utility',
    long_description=readme,
    url='https://github.com/pkgcore/pkgcheck',
    packages=find_packages(),
    install_requires=[
        'lxml',
        'snakeoil>=0.7.2',
        'pkgcore>=0.9.5',
    ],
    scripts=os.listdir('bin'),
    data_files=list(
        pkgdist.data_mapping('share/zsh/site-functions', 'completion/zsh'),
    ),
    cmdclass={
        'sdist': pkgdist.sdist,
        'test': test,
        'build_py': pkgdist.build_py2to3,
        'build_man': pkgdist.build_man,
        'build_docs': pkgdist.build_docs,
        'build_scripts': pkgdist.build_scripts,
        'install_man': pkgdist.install_man,
        'install_docs': pkgdist.install_docs,
    },
    classifiers=[
        'License :: OSI Approved :: BSD License',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
    ],
)
