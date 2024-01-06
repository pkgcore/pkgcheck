DESCRIPTION="Ebuild with deprecated insinto usage"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"

src_install() {
	insinto /etc/conf.d
	doins foo
	insinto /etc/env.d
	doins foo
	insinto /etc/init.d
	doins foo
	insinto /etc/pam.d
	doins foo
	insinto /usr/share/applications
	doins foo
}
