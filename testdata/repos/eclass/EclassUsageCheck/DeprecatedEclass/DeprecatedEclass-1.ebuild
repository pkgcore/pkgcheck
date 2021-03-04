EAPI=7
inherit deprecated2
DESCRIPTION="Ebuild with deprecated eclass usage"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
SLOT="0"
LICENSE="BSD"

src_prepare() {
	deprecated2_public_func
}
