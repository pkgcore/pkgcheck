EAPI=4

DESCRIPTION="Ebuild with unstated USE flag in REQUIRED_USE"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"
IUSE="required"
REQUIRED_USE="|| ( required used )"
