EAPI=7
DESCRIPTION="Ebuild using banned EAPI command"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
SLOT="0"
LICENSE="BSD"

src_install() {
	dohtml doc/*
}
