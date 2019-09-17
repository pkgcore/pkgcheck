EAPI=7
DESCRIPTION="Ebuild with metadata errors in depsets"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
SLOT="0"
LICENSE="BSD"
DEPEND="
	!DependencyCheck/MetadataError
	|| ( stub/stub1:= stub/stub2:= )
	!!stub/stub3:=
"
