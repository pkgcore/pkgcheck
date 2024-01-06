DESCRIPTION="Ebuild specifying KEYWORDS across multiple lines in global scope"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"

if [[ ${PV} == "9999" ]] ; then
	inherit vcs
	KEYWORDS=""
else
	KEYWORDS="amd64 x86"
fi
