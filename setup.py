# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: BSD/GPL2

import os
from distutils.core import setup

from snakeoil import distutils_extensions as snk_distutils

from pkgcore_checks import __version__

class mysdist(snk_distutils.sdist):

    package_namespace = 'pkgcore_checks'
    old_verinfo = False


packages = []
for root, dirs, files in os.walk('pkgcore_checks'):
    if '__init__.py' in files:
        package = root.replace(os.path.sep, '.')
        packages.append(package)

try:
    os.unlink("MANIFEST")
except OSError:
    pass

class test(snk_distutils.test):

    default_test_namespace = 'pkgcore_checks'
    blacklist = frozenset(['pkgcore_checks.plugins'])


class pchecks_build_py(snk_distutils.build_py):

    package_namespace = 'pkgcore_checks'
    generate_verinfo = True


setup(
    name="pkgcore-checks",
    version=__version__,
    license="GPL2",
    author="Brian Harring",
    author_email="ferringb@gmail.com",
    description="pkgcore based ebuild checks- repoman replacement",
    packages=packages,
    py_modules=[
        'pkgcore.plugins.pcheck_config',
        'pkgcore.plugins.pcheck_configurables',
        ],
    scripts=["pcheck", "replay-pcheck-stream"],
    cmdclass={"sdist":mysdist,
        "test":test,
        "build_py":pchecks_build_py,
        }
)
