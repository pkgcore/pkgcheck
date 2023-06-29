_ruby_implementation_depend() {
	local rubypn= rubyslot=

	case $1 in
		ruby27) rubypn="dev-lang/ruby" rubyslot=":2.7" ;;
		ruby30) rubypn="dev-lang/ruby" rubyslot=":3.0" ;;
		ruby31) rubypn="dev-lang/ruby" rubyslot=":3.1" ;;
		ruby32) rubypn="dev-lang/ruby" rubyslot=":3.2" ;;
		*) die "$1: unknown Ruby implementation"
	esac

	echo "$2${rubypn}$3${rubyslot}"
}

_ruby_implementations_depend() {
	local depend _ruby_implementation
	for _ruby_implementation in "${_RUBY_GET_ALL_IMPLS[@]}"; do
		depend="${depend}${depend+ }ruby_targets_${_ruby_implementation}? ( $(_ruby_implementation_depend $_ruby_implementation) )"
	done
	DEPEND="${depend}"
	IUSE="${_RUBY_GET_ALL_IMPLS[*]/#/ruby_targets_}"
	REQUIRED_USE="|| ( ${IUSE} )"
}

_ruby_atoms_samelib_generic() {
	local shopt_save=$(shopt -p -o noglob)
	echo "RUBYTARGET? ("
	for token in $*; do
		case "$token" in
			"||" | "(" | ")" | *"?")
				echo "${token}" ;;
			*])
				echo "${token%[*}[RUBYTARGET(-),${token/*[}" ;;
			*)
				echo "${token}[RUBYTARGET(-)]" ;;
		esac
	done
	echo ")"
	${shopt_save}
}

_ruby_atoms_samelib() {
	local atoms=$(_ruby_atoms_samelib_generic "$*")
    for _ruby_implementation in "${_RUBY_GET_ALL_IMPLS[@]}"; do
        echo "${atoms//RUBYTARGET/ruby_targets_${_ruby_implementation}}"
    done
}

_ruby_get_all_impls() {
	_RUBY_GET_ALL_IMPLS=()

	local i found_valid_impl
	for i in ${USE_RUBY}; do
		case ${i} in
			# removed implementations
			ruby19|ruby2[0-7]|jruby)
				;;
			*)
				found_valid_impl=1
				_RUBY_GET_ALL_IMPLS+=( ${i} )
				;;
		esac
	done

	if [[ -z ${found_valid_impl} ]] ; then
		die "No supported implementation in USE_RUBY."
	fi
}

ruby_add_depend() {
	DEPEND+=" $(_ruby_atoms_samelib "$1")"
}

ruby_add_bdepend() {
	BDEPEND+=" $(_ruby_atoms_samelib "$1")"
}

ruby_add_rdepend() {
	RDEPEND+=" $(_ruby_atoms_samelib "$1")"
}

_ruby_get_all_impls
_ruby_implementations_depend
