EAPI=7

if [[ ${PV} == "9999" ]] ; then
	inherit vcs
fi

DESCRIPTION="Ebuild with conditional eclass usage"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"

src_prepare() {
	[[ ${PV} == "9999" ]] && vcs_public_function
}
