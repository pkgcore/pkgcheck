#!/usr/bin/env python
# Copyright: 2015 Tim Harder <radhermit@gmail.com>
# License: BSD/GPL2

"""Wrapper for commandline scripts."""

from __future__ import absolute_import

from importlib import import_module
import os
import sys


def main(script_name=None):
    if script_name is None:
        script_name = os.path.basename(sys.argv[0])

    try:
        from pkgcore.util import commandline
        script = import_module(
            'pkgcheck.scripts.%s' % script_name.replace("-", "_"))
    except ImportError as e:
        sys.stderr.write(str(e) + '!\n')
        sys.stderr.write(
            'Verify that snakeoil and pkgcore are properly installed '
            'and/or PYTHONPATH is set correctly for python %s.\n' %
            (".".join(map(str, sys.version_info[:3])),))
        if '--debug' in sys.argv:
            raise
        sys.stderr.write('Add --debug to the commandline for a traceback.\n')
        sys.exit(1)

    if getattr(script, 'OptionParser', False):
        commandline.main({None: (script.OptionParser, script.main)})
    else:
        subcommands = getattr(script, 'argparser', None)
        commandline.main(subcommands)


if __name__ == '__main__':
    # we're in a git repo or tarball so add the base dir to the system path
    sys.path.insert(1, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    main(os.path.basename(__file__))
