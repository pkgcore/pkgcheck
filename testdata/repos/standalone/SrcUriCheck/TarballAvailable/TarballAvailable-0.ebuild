EAPI=2

DESCRIPTION="Ebuild with SRC_URI using .zip archive when .tar* is available"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
SRC_URI="
	https://github.com/pkgcore/pkgcheck/archive/${PV}.zip -> ${P}.zip
	https://gitlab.com/pkgcore/pkgcheck/-/archive/${PV}.zip -> ${P}.zip
"
LICENSE="BSD"
SLOT="0"
DEPEND="app-arch/unzip"
