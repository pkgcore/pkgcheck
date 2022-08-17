EAPI=7

DESCRIPTION="Ebuild missing an eclass inherit"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
SLOT="0"
LICENSE="BSD"

src_prepare() {
	inherit_public_func
	unset EBUILD_TEST
}
