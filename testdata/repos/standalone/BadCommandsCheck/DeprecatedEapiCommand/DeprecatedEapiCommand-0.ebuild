EAPI=6

DESCRIPTION="Ebuild using deprecated EAPI command"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"

src_install() {
	dohtml doc/*
}
