EAPI=6

DESCRIPTION="Ebuild using banned commands"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"

pkg_preinst() {
	usermod -s /bin/bash uucp || die
}

pkg_postrm() {
	usermod -s /bin/false uucp || die
}
