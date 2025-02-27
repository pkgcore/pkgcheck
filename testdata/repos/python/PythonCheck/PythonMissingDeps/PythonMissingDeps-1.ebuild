EAPI=8

DISTUTILS_OPTIONAL=1
DISTUTILS_USE_PEP517=setuptools
PYTHON_COMPAT=( pypy3.11 python3_10 )

inherit distutils-r1

DESCRIPTION="Ebuild with missing distutils-r1 PEP517 deps"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"
REQUIRED_USE="python? ( ${PYTHON_REQUIRED_USE} )"

IUSE="python"

RDEPEND="python? ( ${PYTHON_DEPS} )"
