EAPI=7
DESCRIPTION="Ebuild with optfeature suggesting a nonexistent package"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
SLOT="0"
LICENSE="BSD"
KEYWORDS="~amd64"

inherit optfeature

pkg_postinst() {
	optfeature "valid support" stub/stable
	optfeature "broken support" stub/nonexistent
	optfeature "at least one valid support" stub/nonexistent stub/stable
}
