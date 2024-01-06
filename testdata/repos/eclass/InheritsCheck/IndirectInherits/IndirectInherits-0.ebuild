EAPI=7

inherit indirect-inherit

DESCRIPTION="Ebuild relying on indirect inherit"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"

src_prepare() {
	inherit_public_func
	indirect_inherit_public_func
}
