DESCRIPTION="Ebuild with reserved names"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"

prepare_locale() {
	DYNAMIC_DEPS="2"
	_hook_prepare="3"
}

__ORIG_CC="STUB"
EBUILD_SUCCESS_HOOKS="true"
EBUILD_TEST="1"
REBUILD_ALL="1"

post_src_unpack() {
	echo "Larry was here"
}

pre_src_test() {
	echo "Larry was even here"
}
