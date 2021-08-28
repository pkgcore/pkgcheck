# @ECLASS: export-funcs-before-inherit.eclass
# @MAINTAINER:
# Random Person <maintainer@random.email>
# @SUPPORTED_EAPIS: 0 1 2 3 4 5 6 7
# @BLURB: Stub eclass for testing EclassExportFuncsBeforeInherit.

EXPORT_FUNCTIONS src_prepare

inherit another-src_prepare

# @FUNCTION: export-funcs-before-inherit_src_prepare
# @DESCRIPTION:
# My src_prepare.
export-funcs-before-inherit_src_prepare() {
	:
}
