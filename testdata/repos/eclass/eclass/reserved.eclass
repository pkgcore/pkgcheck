# @ECLASS: reserved.eclass
# @MAINTAINER:
# Larry the Cow <larry@example.org>
# @AUTHOR:
# Larry the Cow <larry@example.org>
# @BLURB: Stub eclass.

# @FUNCTION: prepare_locale
# @USAGE:
# @DESCRIPTION:
# Public stub function.
prepare_locale() {
	local DYNAMIC_DEPS
	local prepared
	export EBUILD_DEATH_HOOKS="die"
	echo "${EBUILD}" # This is wrong
	echo "${EBUILD_PHASE}" # This is fine
}

# @ECLASS_VARIABLE: EBUILD_TEST
# @DESCRIPTION:
# Public stub function.
EBUILD_TEST="1"
