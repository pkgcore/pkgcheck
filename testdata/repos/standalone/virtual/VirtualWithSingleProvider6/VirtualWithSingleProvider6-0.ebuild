EAPI=7

DESCRIPTION="virtual with 1 provider, but behind special use flags"
SLOT="0"
IUSE="elibc_glibc"

RDEPEND="
	!elibc_glibc? ( stub/stub1 )
"
