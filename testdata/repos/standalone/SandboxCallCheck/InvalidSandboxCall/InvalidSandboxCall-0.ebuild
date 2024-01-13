DESCRIPTION="Ebuild with invalid sandbox calls"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
SLOT="0"
LICENSE="BSD"

src_compile() {
	addpredict /etc/dfs:/dev/zfs
}

src_test() {
	addwrite /dev /etc
}
