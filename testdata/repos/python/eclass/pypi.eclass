# Copyright 2023 Gentoo Authors
# Distributed under the terms of the GNU General Public License v2

# @ECLASS: pypi.eclass
# @MAINTAINER:
# Michał Górny <mgorny@gentoo.org>
# @AUTHOR:
# Michał Górny <mgorny@gentoo.org>
# @SUPPORTED_EAPIS: 7 8

# @ECLASS_VARIABLE: PYPI_NO_NORMALIZE
# @PRE_INHERIT
# @DEFAULT_UNSET
# @DESCRIPTION:

# @ECLASS_VARIABLE: PYPI_PN
# @PRE_INHERIT
# @DESCRIPTION:
: ${PYPI_PN:=${PN}}

# @FUNCTION: pypi_normalize_name
# @USAGE: <name>
# @DESCRIPTION:
# Normalize the project name according to sdist/wheel normalization
# rules.  That is, convert to lowercase and replace runs of [._-]
# with a single underscore.
#
# Based on the spec, as of 2023-02-10:
# https://packaging.python.org/en/latest/specifications/#package-distribution-file-formats
pypi_normalize_name() {
	local name=${1}
	shopt -s extglob
	name=${name//+([._-])/_}
	echo "${name,,}"
}

# @FUNCTION: pypi_translate_version
# @USAGE: <version>
# @DESCRIPTION:
# Translate the specified Gentoo version into the usual Python
# counterpart.  Assumes PEP 440 versions.
#
# Note that we do not have clear counterparts for the epoch segment,
# nor for development release segment.
pypi_translate_version() {
	local version=${1}
	version=${version/_alpha/a}
	version=${version/_beta/b}
	version=${version/_rc/rc}
	version=${version/_p/.post}
	echo "${version}"
}

# @FUNCTION: pypi_sdist_url
# @USAGE: [--no-normalize] [<project> [<version> [<suffix>]]]
# @DESCRIPTION:
pypi_sdist_url() {
	local normalize=1
	if [[ ${1} == --no-normalize ]]; then
		normalize=
		shift
	fi

	local project=${1-"${PYPI_PN}"}
	local version=${2-"$(pypi_translate_version "${PV}")"}
	local suffix=${3-.tar.gz}
	local fn_project=${project}
	[[ ${normalize} ]] && fn_project=$(pypi_normalize_name "${project}")
	printf "https://files.pythonhosted.org/packages/source/%s" \
		"${project::1}/${project}/${fn_project}-${version}${suffix}"
}

# @FUNCTION: pypi_wheel_name
# @USAGE: [<project> [<version> [<python-tag> [<abi-platform-tag>]]]]
# @DESCRIPTION:
pypi_wheel_name() {
	local project=$(pypi_normalize_name "${1-"${PYPI_PN}"}")
	local version=${2-"$(pypi_translate_version "${PV}")"}
	local pytag=${3-py3}
	local abitag=${4-none-any}
	echo "${project}-${version}-${pytag}-${abitag}.whl"
}

# @FUNCTION: pypi_wheel_url
# @USAGE: [--unpack] [<project> [<version> [<python-tag> [<abi-platform-tag>]]]]
# @DESCRIPTION:
pypi_wheel_url() {
	local unpack=
	if [[ ${1} == --unpack ]]; then
		unpack=1
		shift
	fi

	local filename=$(pypi_wheel_name "${@}")
	local project=${1-"${PYPI_PN}"}
	local version=${2-"$(pypi_translate_version "${PV}")"}
	local pytag=${3-py3}
	printf "https://files.pythonhosted.org/packages/%s" \
		"${pytag}/${project::1}/${project}/${filename}"

	if [[ ${unpack} ]]; then
		echo " -> ${filename}.zip"
	fi
}

if [[ ${PYPI_NO_NORMALIZE} ]]; then
	SRC_URI="$(pypi_sdist_url --no-normalize)"
	S="${WORKDIR}/${PYPI_PN}-$(pypi_translate_version "${PV}")"
else
	SRC_URI="$(pypi_sdist_url)"
	S="${WORKDIR}/$(pypi_normalize_name "${PYPI_PN}")-$(pypi_translate_version "${PV}")"
fi
