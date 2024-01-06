EAPI=8

RUBY_OPTIONAL=1

inherit ruby-ng

DESCRIPTION="Optional inherit with category whitelist"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"

IUSE="test"
RESTRICT="!test? ( test )"
BDEPEND="test? ( dev-ruby/stub )"
