EAPI=7

DESCRIPTION="Use from mirror://pypi and gitlab archive"
HOMEPAGE="https://pkgcore.github.io/pkgcheck/"
SRC_URI="
	mirror://pypi/${PN::1}/${PN}/${P}.tar.gz
	https://gitlab.com/pkgcore/pkgcheck/extra/${PN}/-/archive/${PV}/${P}.tar.bz2 -> ${P}-extra.tar.bz2
"
LICENSE="BSD"
SLOT="0"
