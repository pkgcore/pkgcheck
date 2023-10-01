EAPI=7

DESCRIPTION="Ebuild using banned has_version"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
SLOT="0"
LICENSE="BSD"

src_install() {
	if has_version --host-root stub/stub1; then
		:
	fi
	H=$(best_version --host-root stub/stub1:2)
}
