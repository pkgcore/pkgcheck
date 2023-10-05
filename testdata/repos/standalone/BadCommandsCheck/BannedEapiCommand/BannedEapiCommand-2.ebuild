EAPI=6

DESCRIPTION="Ebuild using banned commands"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
SLOT="0"
LICENSE="BSD"

pkg_preinst() {
	usermod -s /bin/bash uucp || die
}

pkg_postrm() {
	usermod -s /bin/false uucp || die
}
