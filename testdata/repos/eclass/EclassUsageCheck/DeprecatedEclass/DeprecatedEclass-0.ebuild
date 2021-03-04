EAPI=7
inherit deprecated
DESCRIPTION="Ebuild with deprecated eclass usage"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
SLOT="0"
LICENSE="BSD"

src_prepare() {
	deprecated_public_func
}
