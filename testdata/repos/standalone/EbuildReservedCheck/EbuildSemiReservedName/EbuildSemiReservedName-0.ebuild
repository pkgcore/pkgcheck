EAPI=8

DESCRIPTION="Ebuild with semi-reserved names"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
SLOT="0"
LICENSE="BSD"

S=${WORKDIR}  # ok
B=${WORKDIR}  # fail
BDEPEND="app-arch/unzip"  # ok
CDEPEND="app-arch/unzip"  # ok
RDEPEND="${CDEPEND}"  # ok
TDEPEND="app-arch/unzip"  # fail
