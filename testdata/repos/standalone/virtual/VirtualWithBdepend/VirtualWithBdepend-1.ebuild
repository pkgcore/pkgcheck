EAPI=7

DESCRIPTION="Ebuild with unnecessary DEPEND"
SLOT="0"

RDEPEND="|| (
	stub/stub1
	stub/stub2
)
"
BDEPEND="${RDEPEND}"
