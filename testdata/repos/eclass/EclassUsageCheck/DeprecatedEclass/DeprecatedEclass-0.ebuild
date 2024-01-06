EAPI=7
inherit deprecated
DESCRIPTION="Ebuild with deprecated eclass usage"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"

src_prepare() {
	deprecated_public_func
}
