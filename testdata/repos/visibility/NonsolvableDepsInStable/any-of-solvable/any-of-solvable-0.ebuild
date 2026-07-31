EAPI=7
DESCRIPTION="Ebuild with an any-of dep where one all-of branch is solvable"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"
KEYWORDS="amd64"
DEPEND="
	|| (
		( stub/stable stub/masked )
		( stub/stable stub/deprecated )
	)"
