EAPI=7

inherit inherit unused

DESCRIPTION="Ebuild inheriting an unused eclass"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
SLOT="0"
LICENSE="BSD"

src_prepare() {
	inherit_public_func
}
