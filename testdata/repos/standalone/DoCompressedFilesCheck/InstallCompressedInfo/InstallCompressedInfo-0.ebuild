EAPI=7

DESCRIPTION="Ebuild installing compressed info"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"

src_install() {
	doinfo 'test.gz' "${PN}.bz2"
	doinfo "${PN}"
}
