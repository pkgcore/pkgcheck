EAPI=8

DISTUTILS_USE_PEP517=flit
PYTHON_COMPAT=( python3_10 )

inherit distutils-r1

DESCRIPTION="Ebuild with shadowed EPYTEST_TIMEOUT"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"

EPYTEST_PLUGINS=()
EPYTEST_TIMEOUT=1200
distutils_enable_tests pytest
