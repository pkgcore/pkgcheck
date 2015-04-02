#!/usr/bin/env python
# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: BSD/GPL2

from distutils.core import setup
import glob
import os

from snakeoil import distutils_extensions as snk_distutils

from pkgcheck import __version__


class mysdist(snk_distutils.sdist):

    package_namespace = 'pkgcheck'


packages = []
for root, dirs, files in os.walk('pkgcheck'):
    if '__init__.py' in files:
        package = root.replace(os.path.sep, '.')
        packages.append(package)

try:
    os.unlink("MANIFEST")
except OSError:
    pass


class test(snk_distutils.test):

    default_test_namespace = 'pkgcheck'
    blacklist = frozenset(['pkgcheck.plugins'])


class pkgcheck_build_py(snk_distutils.build_py):

    package_namespace = 'pkgcheck'
    generate_verinfo = True


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
    packages=packages,
    requires=[
        'snakeoil (>=0.6.3)',
        'pkgcore (>=0.9)',
    ],
    scripts=glob.glob("bin/*"),
    cmdclass={
        "sdist": mysdist,
        "test": test,
        "build_py": pkgcheck_build_py,
    },
    classifiers=[
        'License :: OSI Approved :: BSD License',
        'License :: OSI Approved :: GNU General Public License v2 (GPLv2)',
        'Programming Language :: Python :: 2.7',
    ],
)
