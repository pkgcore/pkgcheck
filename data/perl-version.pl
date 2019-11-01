#!/usr/bin/perl -w

use strict;

use Gentoo::PerlMod::Version qw( :all );
use IO::Socket::UNIX;

my $SOCK_PATH = $ARGV[0];
if (not defined $SOCK_PATH) {
	die "missing UNIX domain socket path\n";
}

my $client = IO::Socket::UNIX->new(
	Type => SOCK_STREAM(),
	Peer => $SOCK_PATH,
)
	or die("can't connect to python server: $!\n");

$client->autoflush(1);

while (my $line = <$client>) {
	if (defined $line) {
		chomp($line);
		my $version = gentooize_version($line);
		$client->send(sprintf("%02d", length $version));
		$client->send($version);
	}
}
