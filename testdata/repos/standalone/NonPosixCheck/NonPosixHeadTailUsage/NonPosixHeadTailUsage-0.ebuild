DESCRIPTION="Ebuild with non posix head usage"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"

src_prepare() {
	head -1 file > another || die
	head -q file -1 > another || die
	default
}
