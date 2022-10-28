EAPI=7

DESCRIPTION="Ebuild installing compressed info"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
SLOT="0"
LICENSE="BSD"

src_install() {
	doinfo 'test.gz' "${PN}.bz2"
	doinfo "${PN}"
}
