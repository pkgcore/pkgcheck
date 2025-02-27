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
	PYTHON_DEPS="|| ("
	for i in "${PYTHON_COMPAT[@]}"; do
		case ${i} in
			python*)
				slot=${i#python}
				slot=${slot/_/.}
				PYTHON_DEPS+=" dev-lang/python:${slot}"
				;;
			pypy3)
				PYTHON_DEPS+=" dev-lang/pypy:3.10="
				;;
			pypy3*)
				slot=${i#pypy}
				slot=${slot/_/.}
				PYTHON_DEPS+=" dev-lang/pypy:${slot}="
				;;
		esac
	done
	PYTHON_DEPS+=" )"
	PYTHON_REQUIRED_USE='I-DO-NOT-EXIST-IN-PYTHON-ANY-R1'
}
_python_set_impls

python_gen_any_dep() { :; }
python_gen_cond_dep() { :; }
