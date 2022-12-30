EAPI=7
inherit inherit deep-provided-inherit
DESCRIPTION="Ebuild inheriting provided eclass"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
SLOT="0"
LICENSE="BSD"

src_prepare() {
    inherit_public_func
    deep-provided-inherit_public_func
}
