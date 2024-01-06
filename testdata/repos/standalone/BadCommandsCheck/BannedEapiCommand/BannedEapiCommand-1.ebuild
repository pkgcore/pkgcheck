EAPI=7

DESCRIPTION="Ebuild using banned has_version"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"

src_install() {
	if has_version --host-root stub/stub1; then
		:
	fi
	H=$(best_version --host-root stub/stub1:2)
}
