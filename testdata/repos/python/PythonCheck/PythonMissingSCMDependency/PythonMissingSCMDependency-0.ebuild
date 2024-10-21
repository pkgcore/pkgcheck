EAPI=8

DISTUTILS_USE_PEP517=setuptools
PYTHON_COMPAT=( pypy3 python3_10 )

inherit distutils-r1

DESCRIPTION="Ebuild with missing dep on scm"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"

export SETUPTOOLS_SCM_PRETEND_VERSION=${PV}
