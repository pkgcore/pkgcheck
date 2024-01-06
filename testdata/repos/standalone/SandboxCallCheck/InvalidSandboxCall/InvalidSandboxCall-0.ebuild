DESCRIPTION="Ebuild with invalid sandbox calls"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"

src_compile() {
	addpredict /etc/dfs:/dev/zfs
}

src_test() {
	addwrite /dev /etc
}
