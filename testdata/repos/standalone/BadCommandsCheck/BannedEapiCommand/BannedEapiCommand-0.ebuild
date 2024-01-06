EAPI=7

DESCRIPTION="Ebuild using banned EAPI command"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"

src_install() {
	dohtml doc/*
}
