EAPI=9

# NOP stand-ins for the eclass helpers usually called in global scope
python_gen_cond_dep() { :; }
vala_depend() { :; }

DESCRIPTION="Ebuild forking subshells for global scope command substitution"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"

MY_PV=$(ver_cut 1-2) # bad
MY_P=$(ver_cut 1)-$(ver_cut 2) # bad, two forks on one line
MY_OLD=`ver_cut 1` # bad, backtick form
MY_NESTED=$(ver_rs 1-2 '' $(ver_cut 1-3)) # bad, only the outermost is reported
RDEPEND="
	$(vala_depend)
	$(python_gen_cond_dep '
		dev-lang/ruby
	')
" # bad, indented inside a string and spanning several lines

MY_OFFSET=$(( 1 + 2 )) # arithmetic expansion, no subshell
MY_SUBST=${PV/_/-} # parameter expansion, no subshell

src_prepare() {
	local files=$(ls) # function scope, sourced once per phase
	default
}
