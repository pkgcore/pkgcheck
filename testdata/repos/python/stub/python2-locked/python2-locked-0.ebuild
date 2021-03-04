EAPI=7
PYTHON_COMPAT=( python2_7 )

inherit python-r1

DESCRIPTION="Ebuild locked on python2"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"
REQUIRED_USE="${PYTHON_REQUIRED_USE}"

RDEPEND="
	${PYTHON_DEPS}
	stub/python-dep1[${PYTHON_USEDEP}]
"
