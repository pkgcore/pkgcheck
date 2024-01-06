DESCRIPTION="ebuild with shadowed variables"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
S=${WORKDIR}

VAL=

LICENSE="BSD"
SLOT="0"
RESTRICT="!test? ( test )"

RDEPEND="dev-lang/ruby"
DEPEND="${RDEPEND}"
RDEPEND="dev-ruby/stub"

RESTRICT="test"
VAL=5
