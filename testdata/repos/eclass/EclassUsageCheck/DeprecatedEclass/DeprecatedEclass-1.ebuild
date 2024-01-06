EAPI=7
inherit deprecated2
DESCRIPTION="Ebuild with deprecated eclass usage"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"

src_prepare() {
	deprecated2_public_func
}
