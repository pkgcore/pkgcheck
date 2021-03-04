EAPI=7
PYTHON_COMPAT=( python3_7 )

inherit python-r1

DESCRIPTION="Stub ebuild with old PYTHON_COMPAT support"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"
REQUIRED_USE="${PYTHON_REQUIRED_USE}"

RDEPEND="
	${PYTHON_DEPS}
	stub/python-dep-old2[${PYTHON_USEDEP}]
"
