EAPI=8

DISTUTILS_USE_PEP517=flit
PYTHON_COMPAT=( python3_10 )

inherit distutils-r1

DESCRIPTION="Ebuild with non-redundant disable-autoload"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"

EPYTEST_PLUGINS=()
EPYTEST_PLUGIN_AUTOLOAD=1

distutils_enable_tests pytest

python_test() {
	epytest test_one.py

	local -x PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
	epytest test_two.py
}
