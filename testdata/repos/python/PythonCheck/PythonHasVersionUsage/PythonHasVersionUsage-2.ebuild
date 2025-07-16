# Copyright 2025 Gentoo Authors
# Distributed under the terms of the GNU General Public License v2

EAPI=8

PYTHON_COMPAT=( pypy3.11 python3_10 )

inherit python-any-r1

DESCRIPTION="Ebuild that uses has_version with PYTHON_SINGLE_USEDEP"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"

LICENSE="BSD"
SLOT="0"

DEPEND="${PYTHON_DEPS}"
BDEPEND="${PYTHON_DEPS}
	$(python_gen_any_dep '
		dev-util/babeltrace:2[python,${PYTHON_SINGLE_USEDEP}]
	')
"

python_check_deps() {
	python_has_version -b "dev-util/babeltrace:2[python,${PYTHON_SINGLE_USEDEP}]"
}
