EAPI=8

DISTUTILS_USE_PEP517=flit
PYTHON_COMPAT=( python3_10 )

inherit distutils-r1

DESCRIPTION="Ebuild with misplaced EPYTEST vars"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"

distutils_enable_tests pytest

EPYTEST_PLUGIN_AUTOLOAD=1
EPYTEST_PLUGINS=( foo bar baz )
EPYTEST_XDIST=1
: ${EPYTEST_TIMEOUT:=180}

EPYTEST_DESELECT=(
	tests/test_foo.py::test_foo
)
EPYTEST_IGNORE=(
	tests/test_bar.py
)

python_test() {
	: ${EPYTEST_TIMEOUT:=300}
	local EPYTEST_PLUGINS=( "${EPYTEST_PLUGINS[@]}" more )
	EPYTEST_XDIST= epytest
}
