EAPI=7
inherit inherit deep-provided-inherit
DESCRIPTION="Ebuild inheriting provided eclass"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"

src_prepare() {
    inherit_public_func
    deep-provided-inherit_public_func
}
