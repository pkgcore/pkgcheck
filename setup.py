# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: GPL2

from distutils.core import setup
from distutils.command.sdist import sdist
import os

class mysdist(sdist):
    default_format = dict(sdist.default_format)
    default_format["posix"] = "bztar"
    def run(self):
        print "regenning ChangeLog"
        os.system("bzr log > ChangeLog")
        sdist.run(self)

packages = []
for root, dirs, files in os.walk('pkgcore_checks'):
    if '__init__.py' in files:
        package = root.replace(os.path.sep, '.')
        print 'adding package %r' % (package,)
        packages.append(package)

try:
    os.unlink("MANIFEST")
except OSError:
    pass

setup(
    name="pkgcore-checks",
    version="0",
    license="GPL2",
    author="Brian Harring",
    author_email="ferringb@gmail.com",
    description="pkgcore based ebuild checks- repoman replacement",
    packages=packages,
    scripts=["pcheck"],
    cmdclass={"sdist":mysdist}
)
