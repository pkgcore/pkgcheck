DESCRIPTION="Ebuild with non posix tar usage"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"

src_prepare() {
	tar -zx "${A}"
	tar c \
		--owner=0 \
		--group=0 \
		--numeric-owner \
		-C "${S}" . | something
	tar -c -f - -C "${S}" . | something
	tar -c --file - -C "${S}" . | something
	tar -c --file=- -C "${S}" . | something
}
