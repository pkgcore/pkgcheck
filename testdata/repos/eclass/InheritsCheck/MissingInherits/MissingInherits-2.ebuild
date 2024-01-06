EAPI=7

DESCRIPTION="Ebuild missing an eclass inherit"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"

src_prepare() {
	inherit_public_func
	unset EBUILD_TEST
}

inherit_public_func() {
	echo "inherit_public_func" "${LARRY_EASTER_EGG}"
}
