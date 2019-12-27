EAPI=7
DESCRIPTION="Ebuild with optional and blocker deprecated deps"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
SLOT="0"
LICENSE="BSD"
KEYWORDS="~amd64"
RDEPEND="
	!stub/deprecated
	|| ( stub/unstable stub/deprecated )
"
