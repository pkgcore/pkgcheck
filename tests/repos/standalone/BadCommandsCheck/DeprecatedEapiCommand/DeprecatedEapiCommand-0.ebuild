EAPI=6
DESCRIPTION="Ebuild using deprecated EAPI command"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
SLOT="0"
LICENSE="BSD"

src_install() {
	dohtml doc/*
}
