EAPI=8
inherit unquotedvariable
DESCRIPTION="Ebuild with user variable override"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"

EBZR_STORE_DIR="/var/tmp/portage" # FAIL

src_prepare() {
    echo "${EBZR_STORE_DIR}" # ok
}
