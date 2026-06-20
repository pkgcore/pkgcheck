DESCRIPTION="Ebuild with excessive CONFIG_ prefix in CONFIG_CHECK options"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"
KEYWORDS="amd64 x86"

CONFIG_CHECK="~CONFIG_GPIO_SYSFS"

pkg_setup() {
	local CONFIG_CHECK="MTRR !CONFIG_SND_HDA_RECONFIG"
	linux-info_pkg_setup
}
