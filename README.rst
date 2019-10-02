|pypi| |test| |coverage|

========
pkgcheck
========

Dependencies
============

pkgcheck is developed alongside pkgcore_. To run the development version of
pkgcheck you will need the development version of pkgcore.

The metadata.xml checks require lxml to be installed.

Installing
==========

No installation is strictly required, just run the ``pkgcheck`` script and
things should work. For a more permanent install see the following options:

Installing latest pypi release in a virtualenv::

    pip install pkgcheck

Installing from git in a virtualenv::

    git clone https://github.com/pkgcore/pkgcheck.git
    ./pkgcheck/requirements/pip.sh ./pkgcheck

Installing from a tarball or git repo::

    python setup.py install

Tests
=====

A standalone test runner is integrated in setup.py; to run, just execute::

    python setup.py test

In addition, a tox config is provided so the testsuite can be run in a
virtualenv setup against all supported python versions. To run tests for all
environments just execute **tox** in the root directory of a repo or unpacked
tarball. Otherwise, for a specific python version execute something similar to
the following::

    tox -e py36

Notes
=====

Currently full tree scans will use a large amount of memory (up to ~1.7GB) in
part due to pkgcore's restriction design in relation to the expanding use of
transitive use flag dependencies across the tree. To alleviate this
pkgcore.restrictions_ will be refactored, probably leading to splitting
conditionals off into their own set.


.. _`Installing python modules`: http://docs.python.org/inst/
.. _pkgcore: https://github.com/pkgcore/pkgcore
.. _pkgcore.restrictions: https://github.com/pkgcore/pkgcore/issues/80

.. |pypi| image:: https://img.shields.io/pypi/v/pkgcheck.svg
    :target: https://pypi.python.org/pypi/pkgcheck
.. |test| image:: https://travis-ci.org/pkgcore/pkgcheck.svg?branch=master
    :target: https://travis-ci.org/pkgcore/pkgcheck
.. |coverage| image:: https://codecov.io/gh/pkgcore/pkgcheck/branch/master/graph/badge.svg
    :target: https://codecov.io/gh/pkgcore/pkgcheck
