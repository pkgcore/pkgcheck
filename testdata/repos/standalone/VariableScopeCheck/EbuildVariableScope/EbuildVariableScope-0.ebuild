EAPI=7

DESCRIPTION="Ebuild using a variable outside its defined scope"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"

DOC_CONTENTS="Hello ${ROOT}"

src_configure() {
	# EROOT isn't allowed in src_* phases
	econf --sysconfdir="${EROOT}/etc/${PN}"
}

pkg_postinst() {
	# EROOT allowed in pkg_* phases
	ewarn "Read the doc ${EROOT}/usr/share/doc/${PF}/doc."
}
