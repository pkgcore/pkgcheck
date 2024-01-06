EAPI=7

inherit inherit unused

DESCRIPTION="Ebuild inheriting an unused eclass"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"

src_prepare() {
	inherit_public_func
}
