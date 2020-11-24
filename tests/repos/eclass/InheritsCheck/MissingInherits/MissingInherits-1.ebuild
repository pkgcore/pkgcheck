EAPI=7

DESCRIPTION="Ebuild conditionally missing an eclass inherit"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
SLOT="0"
LICENSE="BSD"

# Check currently ignores any missing flagged VCS-eclass usage as
# it assumes it's conditionalized and can't see that.
src_prepare() {
	[[ ${PV} == "9999" ]] && vcs_public_function
}
