EAPI=7

inherit inherit unused

DESCRIPTION="Ebuild using inherited function indirectly"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
SLOT="0"
LICENSE="BSD"

src_prepare() {
	inherit_public_func
}

src_test() {
	edo unused_function
}
