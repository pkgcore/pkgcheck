EAPI=9

DESCRIPTION="Ebuild using banned commands"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"

src_unpack() {
	tar -xzf foo.tar.gz 3 | hexdump -C
	assert "failed"
}

src_install() {
	domo foo.po
}
