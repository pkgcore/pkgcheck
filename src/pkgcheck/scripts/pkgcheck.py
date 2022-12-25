"""pkgcore-based QA utility for ebuild repos

pkgcheck is a QA utility based on **pkgcore**\\(5) that supports scanning
ebuild repositories for various issues.
"""

from pkgcore.util import commandline

argparser = commandline.ArgumentParser(
    description=__doc__, help=False, subcmds=True, script=(__file__, __name__)
)
