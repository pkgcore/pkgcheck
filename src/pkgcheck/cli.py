"""Various command-line specific support."""

import configparser
import logging
import os
import re

from pkgcore.util import commandline
from snakeoil.contexts import patch
from snakeoil.klass import jit_attr_none
from snakeoil.mappings import OrderedSet

from . import const


class Tool(commandline.Tool):
    def main(self):
        # suppress all pkgcore log messages
        logging.getLogger("pkgcore").setLevel(100)
        return super().main()


class ConfigParser(configparser.ConfigParser):
    """ConfigParser with case-sensitive keys (default forces lowercase)."""

    def optionxform(self, option):
        return option


class ConfigFileParser:
    """Argument parser that supports loading settings from specified config files."""

    default_configs = (const.SYSTEM_CONF_FILE, const.USER_CONF_FILE)

    def __init__(self, parser, configs=(), **kwargs):
        super().__init__(**kwargs)
        self.parser = parser
        self.configs = OrderedSet(configs)

    @jit_attr_none
    def config(self):
        return self.parse_config()

    def parse_config(self, configs=()):
        """Parse given config files."""
        configs = configs if configs else self.configs
        config = ConfigParser(default_section=None)
        try:
            for f in configs:
                config.read(f)
        except configparser.ParsingError as e:
            self.parser.error(f"parsing config file failed: {e}")
        return config

    def parse_config_sections(self, namespace, sections):
        """Parse options from a given iterable of config section names."""
        with patch("snakeoil.cli.arghparse.ArgumentParser.error", self._config_error):
            for section in (x for x in sections if x in self.config):
                config_args = [
                    f"--{k}={v}" if v else f"--{k}" for k, v in self.config.items(section)
                ]
                namespace, args = self.parser.parse_known_optionals(config_args, namespace)
                if args:
                    self.parser.error(f"unknown arguments: {'  '.join(args)}")
        return namespace

    def parse_config_options(self, namespace, configs=()):
        """Parse options from config if they exist."""
        configs = [x for x in configs if os.path.isfile(x)]
        if not configs:
            return namespace

        self.configs.update(configs)
        # reset jit attr to force reparse
        self._config = None

        # load default options
        namespace = self.parse_config_sections(namespace, ["DEFAULT"])

        # load any defined checksets -- empty checksets are ignored
        if "CHECKSETS" in self.config:
            for k, v in self.config.items("CHECKSETS"):
                if v:
                    namespace.config_checksets[k] = re.split("[,\n]", v.strip())

        return namespace

    def _config_error(self, message, status=2):
        """Stub to replace error method that notes config failure."""
        self.parser.exit(status, f"{self.parser.prog}: failed loading config: {message}\n")
