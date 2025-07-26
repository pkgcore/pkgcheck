EAPI=8

DISTUTILS_USE_PEP517=flit
PYTHON_COMPAT=( python3_10 )

inherit distutils-r1

DESCRIPTION="Ebuild without EPYTEST_PLUGINS"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"

distutils_enable_tests pytest
