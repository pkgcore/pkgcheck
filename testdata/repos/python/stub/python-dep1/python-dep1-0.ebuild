EAPI=7
PYTHON_COMPAT=( python3_{7,8,9,10} )

inherit python-r1

DESCRIPTION="Stub ebuild with complete PYTHON_COMPAT support"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"
REQUIRED_USE="${PYTHON_REQUIRED_USE}"

RDEPEND="
	${PYTHON_DEPS}
	stub/python-dep2[${PYTHON_USEDEP}]
"
