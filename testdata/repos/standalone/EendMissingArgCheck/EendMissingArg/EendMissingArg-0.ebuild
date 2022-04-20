EAPI=8

DESCRIPTION="Ebuild calling eend without an argument"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"

src_install() {
	ebegin "installing"
	eend
}
