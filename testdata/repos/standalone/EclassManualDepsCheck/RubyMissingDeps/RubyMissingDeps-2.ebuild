EAPI=8

RUBY_OPTIONAL=1

inherit ruby-ng

DESCRIPTION="Optional inherit with category whitelist"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
SLOT="0"
LICENSE="BSD"

IUSE="test"
RESTRICT="!test? ( test )"
BDEPEND="test? ( dev-ruby/stub )"
