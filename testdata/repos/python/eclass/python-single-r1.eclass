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
	local -a use use_deps
	for i in "${PYTHON_COMPAT[@]}"; do
		slot=${i#python}
		slot=${slot/_/.}
		use+=( "python_single_target_${i}" )
		PYTHON_DEPS+=" python_single_target_${i}? ( dev-lang/python:${slot} )"
	done
	IUSE+=" ${use[@]}"
	PYTHON_REQUIRED_USE="^^ ( ${use[@]} )"
	PYTHON_USEDEP=$(IFS=","; echo "${use[*]}")
}
_python_set_impls
