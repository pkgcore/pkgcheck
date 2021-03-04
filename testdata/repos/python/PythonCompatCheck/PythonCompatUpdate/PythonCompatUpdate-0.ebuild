EAPI=7
PYTHON_COMPAT=( python3_7 )

inherit python-r1

DESCRIPTION="Ebuild with potential PYTHON_COMPAT updates"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"
REQUIRED_USE="${PYTHON_REQUIRED_USE}"

RDEPEND="
	${PYTHON_DEPS}
	stub/python-dep1[${PYTHON_USEDEP}]
	!stub/stub1
	stub/stub2[-disabled,exists]
"
