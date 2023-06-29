EAPI=7

USE_RUBY="ruby27 ruby30"
inherit ruby-ng

DESCRIPTION="Ebuild without potential USE_RUBY updates"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"

RDEPEND="
	stub/stub2
"

ruby_add_rdepend "
	stub/ruby-dep-old
"
