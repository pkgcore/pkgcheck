EAPI=7

inherit indirect-inherit

DESCRIPTION="Ebuild relying on indirect inherit"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
SLOT="0"
LICENSE="BSD"

src_prepare() {
	inherit_public_func
	indirect_inherit_public_func
}
