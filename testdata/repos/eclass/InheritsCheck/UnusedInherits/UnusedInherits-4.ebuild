EAPI=8

inherit eapi-conditional

DESCRIPTION="Ebuild calling a function its eclass defines only in EAPI 7"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"

src_prepare() {
	eapi_conditional_func
}
