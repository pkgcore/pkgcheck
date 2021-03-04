EAPI=7
DESCRIPTION="Ebuild uses bad whitespace character"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
SLOT="0"
LICENSE="BSD"

src_test() {
	# bad chars aren't ignored in comments
	cd "${S}"/cpp || die # or inline comments
	default
}
