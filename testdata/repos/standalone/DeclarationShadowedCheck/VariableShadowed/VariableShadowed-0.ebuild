HOMEPAGE="https://github.com/pkgcore/pkgcheck"
DESCRIPTION="ebuild with shadowed variables"
S=${WORKDIR}

VAL=

SLOT="0"
LICENSE="BSD"
RESTRICT="!test? ( test )"

RDEPEND="dev-lang/ruby"
DEPEND="${RDEPEND}"
RDEPEND="dev-ruby/stub"

RESTRICT="test"
VAL=5
