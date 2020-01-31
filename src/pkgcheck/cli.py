"""Various command-line specific support."""

import os
from configparser import ConfigParser

from pkgcore.util import commandline
from snakeoil.cli import arghparse
from snakeoil.klass import jit_attr
from snakeoil.log import suppress_logging


class Tool(commandline.Tool):
    """Suppress log messages globally."""

    def main(self):
        with suppress_logging():
            return super().main()


class ArgumentParser(arghparse.ArgumentParser):
    """Argument parser that supports loading default settings from specified config files."""

    def __init__(self, configs=(), **kwargs):
        super().__init__(**kwargs)
        self.configs = tuple(x for x in set(configs) if os.path.isfile(x))

    @jit_attr
    def config(self):
        """Config file object related to a given parser."""
        config = ConfigParser()
        for f in self.configs:
            config.read(f)
        return config
