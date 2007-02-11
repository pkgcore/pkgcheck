# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: GPL2

from distutils.core import setup, Command
from distutils.command.sdist import sdist
import os, unittest

class TestLoader(unittest.TestLoader):

    """Test loader that knows how to recurse packages."""

    def loadTestsFromModule(self, module):
        """Recurses if module is actually a package."""
        paths = getattr(module, '__path__', None)
        tests = [unittest.TestLoader.loadTestsFromModule(self, module)]
        if paths is None:
            # Not a package.
            return tests[0]
        for path in paths:
            for child in os.listdir(path):
                if (child != '__init__.py' and child.endswith('.py') and
                    child.startswith('test')):
                    # Child module.
                    childname = '%s.%s' % (module.__name__, child[:-3])
                else:
                    childpath = os.path.join(path, child)
                    if not os.path.isdir(childpath):
                        continue
                    if not os.path.exists(os.path.join(childpath,
                                                       '__init__.py')):
                        continue
                    # Subpackage.
                    childname = '%s.%s' % (module.__name__, child)
                tests.append(self.loadTestsFromName(childname))
        return self.suiteClass(tests)


testLoader = TestLoader()


class test(Command):

    """Run our unit tests in a built copy.

    Based on code from setuptools.
    """

    user_options = []

    def initialize_options(self):
        # Options? What options?
        pass

    def finalize_options(self):
        # Options? What options?
        pass

    def run(self):
        build_ext = self.reinitialize_command('build_ext')
        build_ext.inplace = True
        self.run_command('build_ext')
        # Somewhat hackish: this calls sys.exit.
        unittest.main('pkgcore_checks.test', argv=['setup.py', '-v'],
            testLoader=testLoader)


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

from pkgcore_checks import __version__
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
    cmdclass={"sdist":mysdist, "test":test}
)
