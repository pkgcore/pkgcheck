# @ECLASS: distutils-r1.eclass
# @MAINTAINER:
# Python team <python@gentoo.org>
# @AUTHOR:
# Author: Michał Górny <mgorny@gentoo.org>
# Based on the work of: Krzysztof Pawlik <nelchael@gentoo.org>
# @SUPPORTED_EAPIS: 6 7 8
# @PROVIDES: python-r1 python-single-r1

# @ECLASS_VARIABLE: DISTUTILS_OPTIONAL
# @DEFAULT_UNSET
# @DESCRIPTION:

# @ECLASS_VARIABLE: DISTUTILS_DEPS
# @DESCRIPTION:
# See the variable docs in the related gentoo repo eclass.

if [[ ! ${DISTUTILS_SINGLE_IMPL} ]]; then
	inherit python-r1
else
	inherit python-single-r1
fi

_distutils_set_globals() {
	local rdep bdep
	if [[ ${DISTUTILS_USE_PEP517} ]]; then
		if [[ ${DISTUTILS_USE_SETUPTOOLS} ]]; then
			die "DISTUTILS_USE_SETUPTOOLS is not used in PEP517 mode"
		fi

		bdep='
			>=dev-python/gpep517-8[${PYTHON_USEDEP}]
		'
    fi

	if [[ ! ${DISTUTILS_SINGLE_IMPL} ]]; then
		bdep=${bdep//\$\{PYTHON_USEDEP\}/${PYTHON_USEDEP}}
		rdep=${rdep//\$\{PYTHON_USEDEP\}/${PYTHON_USEDEP}}
	else
		[[ -n ${bdep} ]] && bdep="$(python_gen_cond_dep "${bdep}")"
		[[ -n ${rdep} ]] && rdep="$(python_gen_cond_dep "${rdep}")"
	fi

	if [[ ${DISTUTILS_USE_PEP517} ]]; then
        DISTUTILS_DEPS=${bdep}
        readonly DISTUTILS_DEPS
	fi

	if [[ ! ${DISTUTILS_OPTIONAL} ]]; then
		RDEPEND="${PYTHON_DEPS} ${rdep}"
		if [[ ${EAPI} != 6 ]]; then
			BDEPEND="${PYTHON_DEPS} ${bdep}"
		else
			DEPEND="${PYTHON_DEPS} ${bdep}"
		fi
		REQUIRED_USE=${PYTHON_REQUIRED_USE}
	fi
}
_distutils_set_globals
unset -f _distutils_set_globals
