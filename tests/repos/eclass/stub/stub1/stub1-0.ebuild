EAPI=7

inherit missing no-maintainer vcs

DESCRIPTION="Stub ebuild used to suppress unwanted results"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
SLOT="0"
LICENSE="BSD"

src_prepare() {
	missing-docs_documented_func
	vcs_public_function
}
