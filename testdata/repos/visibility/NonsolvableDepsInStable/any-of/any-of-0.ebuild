EAPI=7
DESCRIPTION="Ebuild with an any-of dep where every all-of branch is nonsolvable"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"
KEYWORDS="amd64"
DEPEND="
	|| (
		( stub/stable stub/unstable )
		( stub/stable stub/masked )
	)"
