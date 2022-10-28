EAPI=7

DESCRIPTION="Ebuild installing compressed man pages"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
SLOT="0"
LICENSE="BSD"

src_install() {
	doman 'test.gz' "${PN}.2.bz2"
	newman ${PN}.xz "${PN}.1.xz"
	doman "${PN}"
}
