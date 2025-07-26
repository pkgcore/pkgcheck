EAPI=8

DISTUTILS_USE_PEP517=flit
PYTHON_COMPAT=( python3_10 )

inherit distutils-r1

DESCRIPTION="Ebuild with old-style autoload-disable"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"

distutils_enable_tests pytest

python_test() {
	local -x PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
	epytest
}
