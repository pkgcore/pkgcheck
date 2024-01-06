EAPI=7

DESCRIPTION="Ebuild uses bad whitespace character"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"

src_test() {
	# bad chars aren't ignored in comments
	cd "${S}"/cpp || die # or inline comments
	default
}
