|pypi| |test| |coverage|

========
pkgcheck
========

Dependencies
============

pkgcheck is developed alongside pkgcore_ and snakeoil_. Running pkgcheck from
git will often require both pkgcore and snakeoil from git as well.

For releases, see the required runtime dependencies_.

There are also several optional runtime dependencies that add or extend check
support in various ways if found on the host system including the following:

- git_: supports historical queries for git-based repos and commit-related checks
- requests_: supports various network-related checks
- Gentoo-PerlMod-Version_: supports Perl package version checks
- tree-sitter-bash_: used in checks that inspect the CST of ebuilds and
  eclasess. Must be language version >= 13.

Installing
==========

Installing latest pypi release::

    pip install pkgcheck

Installing from git::

    pip install https://github.com/pkgcore/pkgcheck/archive/master.tar.gz

Installing from a tarball::

    python setup.py install

Usage
=====

Most users will use pkgcheck on the command line via ``pkgcheck scan`` to
target ebuild repos. See the docs_ or the man page for more information on
running pkgcheck.

It's also possible to run pkgcheck natively from python. For example, to output
the results for a given ebuild repo:

.. code-block:: python

    from pkgcheck import scan

    for result in scan(['/path/to/ebuild/repo']):
        print(result)

This allows third party tools written in python to leverage pkgcheck's scanning
functionality for purposes such as CI or VCS commit support.

Tests
=====

A standalone test runner is integrated in setup.py; to run, just execute::

    python setup.py test

In addition, a tox config is provided so the testsuite can be run in a
virtualenv setup against all supported python versions. To run tests for all
environments just execute **tox** in the root directory of a repo or unpacked
tarball. Otherwise, for a specific python version execute something similar to
the following::

    tox -e py39


.. _pkgcore: https://github.com/pkgcore/pkgcore
.. _snakeoil: https://github.com/pkgcore/snakeoil
.. _dependencies: https://github.com/pkgcore/pkgcheck/blob/master/requirements/install.txt
.. _git: https://git-scm.com/
.. _requests: https://pypi.org/project/requests/
.. _Gentoo-PerlMod-version: https://metacpan.org/release/Gentoo-PerlMod-Version
.. _tree-sitter-bash: https://github.com/tree-sitter/tree-sitter-bash
.. _docs: https://pkgcore.github.io/pkgcheck/man/pkgcheck.html

.. |pypi| image:: https://img.shields.io/pypi/v/pkgcheck.svg
    :target: https://pypi.python.org/pypi/pkgcheck
.. |test| image:: https://github.com/pkgcore/pkgcheck/workflows/test/badge.svg
    :target: https://github.com/pkgcore/pkgcheck/actions?query=workflow%3A%22test%22
.. |coverage| image:: https://codecov.io/gh/pkgcore/pkgcheck/branch/master/graph/badge.svg
    :target: https://codecov.io/gh/pkgcore/pkgcheck
