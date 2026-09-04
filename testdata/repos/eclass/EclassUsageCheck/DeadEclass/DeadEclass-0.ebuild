EAPI=7
inherit dead
DESCRIPTION="Ebuild with dead eclass usage"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"

src_prepare() {
	dead_public_func
}
