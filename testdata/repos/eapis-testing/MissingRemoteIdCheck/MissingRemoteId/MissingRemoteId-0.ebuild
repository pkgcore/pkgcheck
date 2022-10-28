EAPI=7

DESCRIPTION="Skip patch and diff urls, and urls behind use flags"
HOMEPAGE="https://pkgcore.github.io/pkgcheck/"
SRC_URI="
	https://github.com/pkgcore/pkgcheck/pull/486.patch -> ${PN}-486.patch
	https://github.com/pkgcore/pkgcheck/pull/486.diff -> ${PN}-486.diff
	test? (
		https://github.com/pkgcore/pkgcheck/archive/v${PV}.tar.gz
		 -> ${P}.gh.tar.gz
	)
"
LICENSE="BSD"
SLOT="0"
IUSE="test"
RESTRICT="!test? ( test )"
