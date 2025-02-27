# Copyright 2022 Gentoo Authors
# Distributed under the terms of the GNU General Public License v2

EAPI=8

PYTHON_COMPAT=( pypy3.11 python3_10 )

inherit python-any-r1

DESCRIPTION="Ebuild that uses has_version"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"

LICENSE="BSD"
SLOT="0"

RDEPEND="
	$(python_gen_cond_dep '
		dev-python/flit_core[${PYTHON_USEDEP}]
	' 3.10)
"
DEPEND="${PYTHON_DEPS}
	$(python_gen_any_dep '
		dev-python/flit_core[${PYTHON_USEDEP}]
	')
"
BDEPEND="${PYTHON_DEPS}
	$(python_gen_any_dep '
		dev-python/lxml[${PYTHON_USEDEP}]
		dev-python/gpep517[${PYTHON_USEDEP}]
	')
"

python_check_deps() {
	use test || return 1
	has_version "dev-python/lxml[${PYTHON_USEDEP}]" &&
	has_version -r "dev-python/lxml[${PYTHON_USEDEP}]" &&
	python_has_version "dev-python/gpep517[${PYTHON_USEDEP}]" &&
	python_has_version "dev-python/flit_core[${PYTHON_USEDEP}]"
}
