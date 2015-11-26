|pypi| |test| |coverage|

========
pkgcheck
========

Dependencies
============

pkgcheck is developed alongside pkgcore_. To run the development version of
pkgcheck you will need the development version of pkgcore.

The metadata.xml checks require either xmllint (installed as part of
libxml2) or the python bindings to libxml2 (installed as part of
libxml2 with USE=python), with the latter preferred for speed reasons.

Installing
==========

No installation is strictly required, just run the ``pkgcheck`` script and
things should work. For a more permanent install see the following options:

Installing latest pypi release in a virtualenv::

    pip install pkgcheck

Installing from git in a virtualenv (latest snakeoil/pkgcore are often required)::

    pip install https://github.com/pkgcore/snakeoil/archive/master.tar.gz
    pip install https://github.com/pkgcore/pkgcore/archive/master.tar.gz
    pip install https://github.com/pkgcore/pkgcheck/archive/master.tar.gz

Installing from a tarball or git repo::

    python setup.py install
    pplugincache pkgcheck

Notes
=====

Currently full tree scans will use a large amount of memory (up to ~1.7GB) in
part due to pkgcore's restriction design in relation to the expanding use of
transitive use flag dependencies across the tree. To alleviate this
pkgcore.restrictions_ will be refactored, probably leading to splitting
conditionals off into their own set.

Configuration
=============

No configuration is required, but some configuration makes ``pkgcheck``
easier to use.

Suites
------

With no configuration it will try to guess the repository to use based
on your working directory and the list of repositories pkgcore knows
about. This will usually not quite work because the same location
often has multiple "repositories" with a slightly different
configuration and ``pkgcheck`` cannot guess which one to use.

Defining "suites" in the configuration solves this ambiguity. A
"suite" contains a target repository, optionally a source repository
to use as a base and optionally a set of checks to run. If there is a
single suite with a target repository containing the current directory
it is used. So with the following suite definition in
``~/.pkgcore.conf``::

  [pkgcheck-gentoo-suite]
  class=pkgcheck.base.Suite
  target_repo=gentoo

you can run ``pkgcheck`` with no further arguments inside your portage
directory and it will do the right thing.

For use with overlays you need to define the "source" repo too::

  [pkgcheck-overlay-suite]
  class=pkgcheck.base.Suite
  target_repo=/usr/local/portage/private
  src_repo=gentoo

(the ``target_repo`` and ``src_repo`` settings are both names of
repository sections, not arbitrary filesystem paths).

See Overlays_ for more information on ``src_repo``.

Finally, you can define a different checkset per suite::

  [pkgcheck-gentoo-suite]
  class=pkgcheck.base.Suite
  target_repo=gentoo
  checkset=no-arch-checks

This disables checks that are not interesting unless you can set
stable keywords for this suite. See Checksets_ for more information.

Instead of relying on the working directory to pick the right suite
you can specify one explicitly with ``pkgcheck --suite``.

Checksets
---------

By default ``pkgcheck`` runs all available checks. This is not always
desired. For example, checks about missing stable keywords are often
just noise in the output for ebuild devs. A checkset defines a subset
of checks to run. There are two kinds: one enabling a specific set of
checks and one running every available check except for the specified
ones. Examples::

  [no-arch-checks]
  class=pkgcheck.base.Blacklist
  patterns=unstable_only stale_unstable imlate

  [only-arch-checks]
  class=pkgcheck.base.Whitelist
  patterns=unstable_only stale_unstable imlate

The first disables the three specified checks, the second enables only
those three. For available names see ``pkgcheck --list-checks``.

``patterns`` is a whitespace-separated list. If the values are strings
they need to match a component of the name in ``--list-checks``
exactly. If it looks like a regexp (currently defined as "contains a +
or \*") this needs to match the entire name.

Checksets called ``no-arch-checks`` and ``all-checks`` are defined by
default.

There are various ways to pick the checkset to use: ``pquery
--checkset``, the checkset setting of a suite and setting
``default=true`` on a checkset in the configuration.

Overlays
--------

Checking just an overlay does not work very well since pkgcheck
needs to know about profiles and checks if all dependencies are
available. To do this you will usually have to specify a base or
"source" repo to pull this data from. You can set this with ``pkgcheck
--overlayed-repo`` or the ``pkgcheck -o`` shorthand, or you can set it
in the configuration file as part of a suite__ definition.

__ Suites_

Reporters
---------

By default the output is in a colorful human-readable format. For full
tree checks this format may not be optimal since it is a bit hard to
grep. To use an output format that prints everything on one line, put
this in your configuration::

  [pkgcheck-plain-reporter]
  class=pkgcheck.reporters.plain_reporter
  default=true

To use a non-default reporter use ``pkgcheck --reporter``. To see the
reporters available use ``pconfig configurables
pkgcheck_reporter_factory``.


.. _`Installing python modules`: http://docs.python.org/inst/
.. _pkgcore: https://github.com/pkgcore/pkgcore
.. _pkgcore.restrictions: https://github.com/pkgcore/pkgcore/issues/80

.. |pypi| image:: https://img.shields.io/pypi/v/pkgcheck.svg
    :target: https://pypi.python.org/pypi/pkgcheck
.. |test| image:: https://travis-ci.org/pkgcore/pkgcheck.svg?branch=master
    :target: https://travis-ci.org/pkgcore/pkgcheck
.. |coverage| image:: https://coveralls.io/repos/pkgcore/pkgcheck/badge.png?branch=master
    :target: https://coveralls.io/r/pkgcore/pkgcheck?branch=master
