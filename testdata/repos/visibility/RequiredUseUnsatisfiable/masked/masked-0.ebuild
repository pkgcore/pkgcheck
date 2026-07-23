EAPI=7
DESCRIPTION="Ebuild with REQUIRED_USE unsatisfiable due to masked flags"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"
KEYWORDS="amd64"
IUSE="flag_a flag_b flag_c"
REQUIRED_USE="^^ ( flag_a flag_b flag_c )"
