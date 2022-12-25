"""Logging utilities."""

import logging

# The logging system will call this automagically if its module-level logging
# functions are used. We call it explicitly to make sure something handles
# messages sent to our non-root logger. If the root logger already has handlers
# this is a noop, and if someone attaches a handler to our logger that
# overrides the root logger handler.
logging.basicConfig()

logger = logging.getLogger("pkgcheck")
