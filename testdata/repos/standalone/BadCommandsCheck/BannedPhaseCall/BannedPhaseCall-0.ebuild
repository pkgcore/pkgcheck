EAPI=8

DESCRIPTION="Ebuild calls phase function directly"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
SLOT="0"
LICENSE="BSD"

pkg_postinst() {
	echo "something"
}

pkg_postrm() {
	pkg_postinst
}
