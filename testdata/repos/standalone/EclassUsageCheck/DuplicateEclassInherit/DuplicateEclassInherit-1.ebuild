EAPI=7

if [[ ${PV} == "9999" ]] ; then
	EVCS_REPO_URI="https://github.com/pkgcore/pkgcheck.git"
	inherit stub vcs
else
	inherit stub
	KEYWORDS="~amd64 ~x86"
fi

DESCRIPTION="Ebuild with conditional, duplicate eclass inherit"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"
