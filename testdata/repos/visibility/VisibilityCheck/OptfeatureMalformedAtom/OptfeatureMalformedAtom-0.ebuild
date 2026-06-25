EAPI=7
DESCRIPTION="Ebuild with optfeature passing a malformed atom"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
SLOT="0"
LICENSE="BSD"
KEYWORDS="~amd64"

inherit optfeature

pkg_postinst() {
	optfeature "broken support" "=stub/stable"
}
