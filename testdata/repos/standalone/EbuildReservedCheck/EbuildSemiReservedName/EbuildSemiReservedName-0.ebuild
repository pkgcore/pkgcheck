EAPI=8

DESCRIPTION="Ebuild with semi-reserved names"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"

S=${WORKDIR}  # ok
B=${WORKDIR}  # fail

LICENSE="BSD"
SLOT="0"

CDEPEND="app-arch/unzip"  # ok
RDEPEND="${CDEPEND}"  # ok
BDEPEND="app-arch/unzip"  # ok
TDEPEND="app-arch/unzip"  # fail
