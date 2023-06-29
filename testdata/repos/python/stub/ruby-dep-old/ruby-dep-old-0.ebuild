EAPI=7

USE_RUBY="ruby27 ruby30"

inherit ruby-ng

DESCRIPTION="Stub ebuild with old USE_RUBY support"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"

RDEPEND="
	stub/stub2
"
