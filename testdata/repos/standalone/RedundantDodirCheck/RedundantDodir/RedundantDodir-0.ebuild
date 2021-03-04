EAPI=7
DESCRIPTION="Ebuild with redundant dodir calls"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
SLOT="0"
LICENSE="BSD"

src_install() {
	touch blah
	dodir /foo/bar
	insinto /foo/bar
	doins blah

	# make sure differing paths aren't flagged
	dodir /foo/bar
	insinto /foo/bar2
	doins blah

	touch blaz
	dodir /foo/bin
	exeinto /foo/bin
	doexe blaz

	touch blob
	dodir /foo/doc
	docinto /foo/doc
	dodoc blob
}
