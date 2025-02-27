# @ECLASS_VARIABLE: PYTHON_DEPS
# @DESCRIPTION:
# See the variable docs in the related gentoo repo eclass.

# @ECLASS_VARIABLE: PYTHON_USEDEP
# @DESCRIPTION:
# See the variable docs in the related gentoo repo eclass.

# @ECLASS_VARIABLE: PYTHON_REQUIRED_USE
# @DESCRIPTION:
# See the variable docs in the related gentoo repo eclass.

_python_set_impls() {
	local i slot
	local -a use
	for i in "${PYTHON_COMPAT[@]}"; do
		use+=( "python_targets_${i}" )
		case ${i} in
			python*)
				slot=${i#python}
				slot=${slot/_/.}
				PYTHON_DEPS+=" python_targets_${i}? ( dev-lang/python:${slot} )"
				;;
			pypy3)
				PYTHON_DEPS+=" python_targets_${i}? ( dev-lang/pypy:3.10= )"
				;;
			pypy3*)
				slot=${i#pypy}
				slot=${slot/_/.}
				PYTHON_DEPS+=" python_targets_${i}? ( dev-lang/pypy:${slot}= )"
				;;
		esac
	done
	IUSE+=" ${use[@]}"
	PYTHON_REQUIRED_USE="|| ( ${use[@]} )"
	PYTHON_USEDEP=$(IFS=","; echo "${use[*]}")
}
_python_set_impls
