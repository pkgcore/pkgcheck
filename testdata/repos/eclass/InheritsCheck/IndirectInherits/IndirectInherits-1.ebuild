EAPI=7

inherit deep-provided-inherit

DESCRIPTION="Ebuild relying on indirect inherit"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"

src_prepare() {
	inherit_public_func
	deep-provided-inherit_public_func
}
