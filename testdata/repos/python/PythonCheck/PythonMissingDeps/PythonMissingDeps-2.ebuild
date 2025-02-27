EAPI=8

DISTUTILS_OPTIONAL=1
DISTUTILS_USE_PEP517=no
PYTHON_COMPAT=( pypy3.11 python3_10 )

inherit distutils-r1

DESCRIPTION="Ebuild with correct distutils-r1 PEP517 deps (PEP517=no)"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"

IUSE="python"
REQUIRED_USE="python? ( ${PYTHON_REQUIRED_USE} )"

RDEPEND="python? ( ${PYTHON_DEPS} )"
