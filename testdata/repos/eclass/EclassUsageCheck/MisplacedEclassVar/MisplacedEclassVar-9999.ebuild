EAPI=7

if [[ "${PV}" == 9999 ]] ; then
	inherit vcs
	PRE_INHERIT_VAR="foo"
fi

inherit pre-inherit

DESCRIPTION="Ebuild with properly set pre-inherit eclass variable"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"

src_prepare() {
	default
	[[ ${PV} == 9999 ]] && vcs_public_function
}
