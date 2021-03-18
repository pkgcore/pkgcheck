DESCRIPTION="Ebuild specifying KEYWORDS across multiple lines in global scope"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
SLOT="0"
LICENSE="BSD"

if [[ ${PV} == "9999" ]] ; then
	inherit vcs
	KEYWORDS=""
else
	KEYWORDS="amd64 x86"
fi
