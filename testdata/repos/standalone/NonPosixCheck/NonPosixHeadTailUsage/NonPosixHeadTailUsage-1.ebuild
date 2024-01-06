DESCRIPTION="Ebuild with non posix head usage"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"

src_prepare() {
	tail -1 file > another || die
	tail -q file -1 > another || die
	tail -qn file +1 > another || die
	default
}
