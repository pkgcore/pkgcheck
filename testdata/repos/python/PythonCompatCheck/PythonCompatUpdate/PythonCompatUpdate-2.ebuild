EAPI=7
PYTHON_COMPAT=( python3_{7,8} )

inherit python-any-r1

DESCRIPTION="Ebuild with potential PYTHON_COMPAT updates"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"

DEPEND="${PYTHON_DEPS}"
