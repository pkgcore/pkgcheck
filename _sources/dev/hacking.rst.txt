=====================
Architecture overview
=====================

If you want to add a check or frontend to pkgcheck you should
probably read this thing first. If you only want to add a check you
should only read the first section ("For everyone"). After that is
extra documentation on adding feed types and some of the internals.

For everyone
============

Addons
------

Most interesting objects are addons. The interface is defined in
base.py. They can have "dependencies" on other addons (by class): all
addons referenced by the required_addons class attribute of an active
addon are also active (and this applies recursively, of course).

Before they are instantiated the class (or static) methods
mangle_argparser and check_args are used to modify the argparse
process. At this point all available checks (and their dependencies)
are active addons. After the commandline is parsed all checks that end
up being active after parsing the commandline are active addons, and
those are instantiated. They receive the argparse instance
followed by the (instantiated) addons they depend on as positional
arguments to __init__.

(The reason for the two "phases" here (argparse mangling before
instantiation) is we want the addons to influence the way options are
parsed while we cannot instantiate them before options are parsed
(since we want to pass the values object and since we only want to
instantiate the ones that end up "selected" according to commandline
settings). The reason for the dependency system used here is to
provide a place to put options and state shared between multiple
checkers (without putting everything on a single global object).)

Checkers, feeds
---------------

What a checker actually *is* is not well defined at the moment, but
everything subclassing base.Template and setting a feed_type attribute
is definitely a checker. Template subclasses Addon, so they are all
also addons. Their feed_type attribute should be set to one of the
feed types defined in base.py. Their feed method will be called with
an iterator producing values of a type depending on their feed_type.
Currently available are versioned_feed which feeds single package
objects and package_feed, category_feed and repository_feed which
produce sequences of packages.

Whatever your feed type is, the first thing you should do with
everything you get out of the feed is "yield" it. The "feeder" and all
the checks are chained together, each yielding objects to the next. So
none of them should modify the data passed to them, and all of them
should yield *everything* to the next checker.

The second argument to their feed method is a Reporter instance (again
defined in base.py) to pass Report instances on to.

Scope
-----

An extra feature available to the feeders is their "scope" attribute.
This is somewhat similar to their feed_type. The difference is roughly
that feed_type must match *exactly* and scope indicates a *minimum*
requirement. This is mainly used by the transforms, but for certain
checks it is also useful to get "fed" single versions per iteration
but only if the check is run on the entire repository. Using a
repository feed would have the same effect of only running your check
if the entire repository is being checked, but requires building a
huge sequence containing all packages in memory before your check
runs. So if you can operate on fewer packages at a time, use a
"smaller" feed and scope.


Checker discovery
-----------------

Checkers are picked up by using pkgcore's plugin mechanism. For
writing a simple custom checker the easiest thing to do is putting the
entire thing in a single file including the pkgcore_plugins
registration dictionary. See core_checks.py for what such a dictionary
looks like. Then put it in a directory called pkgcheck/plugins/
on your PYTHONPATH. So if you have a system-wide pkgcheck
installation you can put your own plugin in
~/lib/python/pkgcheck/plugins/mycheck.py and run
PYTHONPATH=$HOME/lib/python pkgcheck ... to use the check (without
having to install a local copy of pkgcheck and putting the check
inside it).

For those who need more feed types
==================================

Transforms
----------

Usually the checks should run in a single "pipeline": looping over the
packages once uses various caches (not just inside pkgcheck but
also the os disk cache) more efficiently. This is accomplished by
applying "transforms" to the package iterator which change the feed
type. They are very similar to checks, but they do not yield the same
thing they receive. Most (currently all) of them are defined in
feeds.py.

As you can see the way they set their input is a bit different from a
check. Because some simple operations like "Yield the first thing of
every value handed in" can be used for more than one "transformation"
they have more than one source and target feed type. For each of these
they can set their required scope and an integer indicating the "cost"
of this operation. These are currently set to mostly random values,
but the idea is they will allow the plugger to do a better job once
the number of feed types, sources and transforms grows.

There is no way to change the scope. The scope is assumed to be
constant for the entire pipeline.

Performance pitfalls
--------------------

As indicated earlier the checks should run in a single pipeline. This
pipeline is really a *line*: it is not possible to "fork" the iterator
without using potentially unlimited temporary storage. This is a
deficiency of the way iterators are used here. This makes it very
important that there are transforms available from all possible feeds
*and* back.

An example: if the only available source is one generating a
versioned_feed (single package objects), there are transforms from
that to an ebuild_feed producing ebuild source lines and a
package_feed producing sequences of package objects for all versions
in a package, and checks of all those feed types are active, then the
entire repository will be looped over twice: once for the
versioned_feed checkers and either the package_feed or ebuild_feed
checkers, once for the remaining feed type. To avoid the second loop
register a transform back from package_feed and ebuild_feed to
versioned_feed.

Sources
-------

Currently there is only one source, defined in feeds.py.

Registration
------------

Transforms are discovered the same way as checks are: the pkgcore
plugin system. See core_checks.py. The single available feed is
currently hardcoded. This will probably change in the future, but
exactly how remains to be seen.

For pkgcheck internals hackers
==============================

Commandline frontend
--------------------

The frontend code uses pkgcore's commandline utilities module and lives in the
pkgcheck.scripts.pkgcheck module. It is pretty straightforward, although how
control flows through this module is not obvious without knowing how pkgcore's
commandline utils are used:

- pkgcore's commandline glue instantiates the argument parser
- it pulls up all available checks and transforms through the plugin system
- grab all addon dependencies too
- give them a chance to mangle the parser
- the commandline glue parses options, triggering various argparse actions,
  which calls check_args on all addon classes).
- if option parsing succeeded the commandline glue calls main
- main instantiates all active addons and sources
- the autoplugger builds one or more pipelines
- main runs the pipelines

Autoplugger
-----------

The autoplugger gets handed a bunch of "sink", transform and source
instances and builds pipelines from them. It is a hack that relies on
a fair amount of brute force to do its job, but so far it has been
sufficient. It is still a moving target, so its design (if it has one)
is not documented here. Use the source and do not forget about the
tests (it does not have as many as it should but there are a bunch,
and running the tests with debug mode forced (hacked) on should give
some idea of what's what).
