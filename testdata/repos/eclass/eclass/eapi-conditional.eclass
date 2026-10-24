# @ECLASS: eapi-conditional.eclass
# @MAINTAINER:
# Random Person <maintainer@random.email>
# @SUPPORTED_EAPIS: 7 8
# @BLURB: Stub eclass with a function defined only for some EAPIs.

if [[ ${EAPI} == 7 ]]; then
# @FUNCTION: eapi_conditional_func
# @USAGE:
# @DESCRIPTION:
# Public stub function, defined only in EAPI 7.
eapi_conditional_func() { :; }
fi
