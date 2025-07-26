EAPI=8

DISTUTILS_USE_PEP517=flit
PYTHON_COMPAT=( python3_10 )

inherit distutils-r1

DESCRIPTION="Ebuild reenabling autoload"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"

EPYTEST_PLUGINS=()

distutils_enable_tests pytest

python_test() {
	epytest test_one.py

	unset PYTEST_DISABLE_PLUGIN_AUTOLOAD
	epytest test_two.py
}
