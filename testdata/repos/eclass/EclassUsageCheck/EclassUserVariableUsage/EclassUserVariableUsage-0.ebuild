EAPI=8
inherit unquotedvariable
DESCRIPTION="Ebuild with user variable override"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
SLOT="0"
LICENSE="BSD"

EBZR_STORE_DIR="/var/tmp/portage" # FAIL

src_prepare() {
    echo "${EBZR_STORE_DIR}" # ok
}
