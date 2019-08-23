EAPI=2
DESCRIPTION="Ebuild with SRC_URI using .zip archive when .tar* is available"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
SRC_URI="
	https://github.com/pkgcore/pkgcheck/archive/${PV}.zip -> ${P}.zip
	https://gitlab.com/pkgcore/pkgcheck/-/archive/${PV}.zip -> ${P}.zip
"
SLOT="0"
LICENSE="BSD"
DEPEND="app-arch/unzip"
