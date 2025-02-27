# Copyright 2022 Gentoo Authors
# Distributed under the terms of the GNU General Public License v2

EAPI=8

PYTHON_COMPAT=( pypy3.11 python3_10 )

inherit python-any-r1

DESCRIPTION="Ebuild that uses has_version"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"

LICENSE="BSD"
SLOT="0"

# In this file I check edge cases for the parser:
# - no args for $(python_gen_any_dep)
# - usage of \$ is replaced with $
# - unable to parse atom (because of ${PV}) - skip the check for it

DEPEND="${PYTHON_DEPS}"
BDEPEND="${PYTHON_DEPS}
	$(python_gen_any_dep)
	$(python_gen_any_dep "
		dev-python/mako[\${PYTHON_USEDEP}]
	")
	$(python_gen_any_dep "
		dev-python/tempest[\${PYTHON_USEDEP}]
		~dev-python/lit-${PV}[\${PYTHON_USEDEP}]
	")
"

dummy() { :; }

python_check_deps() {
	python_has_version "dev-python/mako[${PYTHON_USEDEP}]"
	# won't report tempest & lit as unable to parse atom string
}
