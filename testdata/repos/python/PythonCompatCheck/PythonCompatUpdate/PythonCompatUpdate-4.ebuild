EAPI=7
PYTHON_COMPAT=( python3_{7..10} python3_13t pypy3 pypy3_11 )

inherit python-any-r1

DESCRIPTION="Ebuild with potential PYTHON_COMPAT updates"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"

DEPEND="${PYTHON_DEPS}"
