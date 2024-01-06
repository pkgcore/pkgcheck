EAPI=4

DESCRIPTION="Ebuild with deprecated insinto usage"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"

src_install() {
	insinto /usr/share/doc/${PF}
	doins foo
	insinto /usr/share/doc/"${PF}"
	doins bar
	insinto /usr/share/doc/${PF}/
	doins -r html
	insinto /usr/share/doc/${PF}/examples
	doins samples/*
	insinto /usr/share/doc/"${PF}"/examples
	doins foo/examples/*
}
