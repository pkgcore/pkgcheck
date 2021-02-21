"""pkgcore-based QA utility for ebuild repos

pkgcheck is a QA utility based on **pkgcore**\\(5) that supports scanning
ebuild repositories for various issues.
"""

from pkgcore.util import commandline

argparser = commandline.ArgumentParser(
    description=__doc__, script=(__file__, __name__))

subparsers = argparser.add_subparsers()
subparsers.add_command('scan')
subparsers.add_command('cache')
subparsers.add_command('ci')
subparsers.add_command('replay')
subparsers.add_command('show')
