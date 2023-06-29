EAPI=7

USE_RUBY="ruby27 ruby30 ruby31 ruby32"

inherit ruby-ng

DESCRIPTION="Stub ebuild with complete USE_RUBY support"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"

RDEPEND="
	stub/stub1
"
