EAPI=7
PYTHON_COMPAT=( python3_{8..10} pypy3_11 )

inherit python-r1

DESCRIPTION="Ebuild with PYTHON_COMPAT impls dropped compared to older versions"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"
REQUIRED_USE="${PYTHON_REQUIRED_USE}"

RDEPEND="${PYTHON_DEPS}"
