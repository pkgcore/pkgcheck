EAPI=7

DESCRIPTION="Ebuild installing compressed man pages"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"

src_install() {
	doman 'test.gz' "${PN}.2.bz2"
	newman ${PN}.xz "${PN}.1.xz"
	doman "${PN}"
}
