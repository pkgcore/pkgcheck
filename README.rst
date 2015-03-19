|test|

========
pkgcheck
========

Dependencies
============

pkgcheck is developed alongside pkgcore. To run the development version
of pkgcheck you will need the development version of pkgcore. Otherwise
the 0.x version numbers need to match.

The metadata.xml checks require either xmllint (installed as part of
libxml2) or the python bindings to libxml2 (installed as part of
libxml2 with USE=python), with the latter preferred for speed reasons.

Installation
============

No installation is strictly required: just run the ``pcheck`` script and
as long as you are not root things should work. If you want to make
pkgcheck available system-wide use the provided ``setup.py``
(see `Installing python modules`_ for details).

Configuration
=============

No configuration is required, but some configuration makes ``pcheck``
easier to use.

Suites
------

With no configuration it will try to guess the repository to use based
on your working directory and the list of repositories pkgcore knows
about. This will usually not quite work because the same location
often has multiple "repositories" with a slightly different
configuration and ``pcheck`` cannot guess which one to use.

Defining "suites" in the configuration solves this ambiguity. A
"suite" contains a target repository, optionally a source repository
to use as a base and optionally a set of checks to run. If there is a
single suite with a target repository containing the current directory
it is used. So with the following suite definition in
``~/.pkgcore.conf``::

  [pcheck-portdir-suite]
  class=pkgcheck.base.Suite
  target_repo=portdir

you can run ``pcheck`` with no further arguments inside your portage
directory and it will do the right thing.

For use with overlays you need to define the "source" repo too::

  [pcheck-overlay-suite]
  class=pkgcheck.base.Suite
  target_repo=/usr/local/portage/private
  src_repo=portdir

(the ``target_repo`` and ``src_repo`` settings are both names of
repository sections, not arbitrary filesystem paths).

See Overlays_ for more information on ``src_repo``.

Finally, you can define a different checkset per suite::

  [pcheck-portdir-suite]
  class=pkgcheck.base.Suite
  target_repo=portdir
  checkset=no-arch-checks

This disables checks that are not interesting unless you can set
stable keywords for this suite. See Checksets_ for more information.

Instead of relying on the working directory to pick the right suite
you can specify one explicitly with ``pcheck --suite``.

Checksets
---------

By default ``pcheck`` runs all available checks. This is not always
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
those three. For available names see ``pcheck --list-checks``.

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
"source" repo to pull this data from. You can set this with ``pcheck
--overlayed-repo`` or the ``pcheck -o`` shorthand, or you can set it
in the configuration file as part of a suite__ definition.

__ Suites_

Reporters
---------

By default the output is in a colorful human-readable format. For full
tree checks this format may not be optimal since it is a bit hard to
grep. To use an output format that prints everything on one line, put
this in your configuration::

  [pcheck-plain-reporter]
  class=pkgcheck.reporters.plain_reporter
  default=true

To use a non-default reporter use ``pcheck --reporter``. To see the
reporters available use ``pconfig configurables
pcheck_reporter_factory``.


.. _`Installing python modules`: http://docs.python.org/inst/

.. |test| image:: https://travis-ci.org/pkgcore/pkgcheck.svg?branch=master
    :target: https://travis-ci.org/pkgcore/pkgcheck
