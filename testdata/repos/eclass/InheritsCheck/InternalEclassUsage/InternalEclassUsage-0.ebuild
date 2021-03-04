EAPI=7

inherit inherit

DESCRIPTION="Ebuild using an internal eclass function"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
SLOT="0"
LICENSE="BSD"

src_prepare() {
	inherit_public_func
	_inherit_internal_func
}
