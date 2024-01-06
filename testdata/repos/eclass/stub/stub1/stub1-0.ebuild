EAPI=7

inherit missing no-maintainer replacement vcs

DESCRIPTION="Stub ebuild used to suppress unwanted results"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"

src_prepare() {
	missing-docs_documented_func
	replacement_public_func
	vcs_public_function
}
