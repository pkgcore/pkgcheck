EAPI=8

DESCRIPTION="Ebuild calls phase function directly"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"

pkg_postinst() {
	echo "something"
}

pkg_postrm() {
	pkg_postinst
}
