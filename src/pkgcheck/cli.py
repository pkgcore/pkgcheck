"""Various command-line specific support."""

from pkgcore.util import commandline
from snakeoil.log import suppress_logging


class Tool(commandline.Tool):
    """Suppress log messages globally."""

    def main(self):
        with suppress_logging():
            return super().main()
