DESCRIPTION="Ebuild with non posix head usage"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
SLOT="0"
LICENSE="BSD"

src_prepare() {
	head -1 file > another || die
	head -q file -1 > another || die
	default
}
