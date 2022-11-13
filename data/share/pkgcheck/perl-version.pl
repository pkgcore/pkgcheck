#!/usr/bin/perl -w
use 5.010;

use strict;

use Gentoo::PerlMod::Version "gentooize_version";

# forcibly flush stdout after every line
STDOUT->autoflush(1);

# When running non-interactively assume we're running under
# pkgcheck and tell the python-side we're up.
unless (-t STDOUT) {
	say "ready";
}

while (my $line = <STDIN>) {
	chomp($line);
	say gentooize_version($line);
}
