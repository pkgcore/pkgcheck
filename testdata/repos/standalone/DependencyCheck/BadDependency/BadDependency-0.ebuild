EAPI=7

DESCRIPTION="Ebuild with bad dependencies"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"
DEPEND="
	!DependencyCheck/BadDependency
	|| ( stub/stub1:= stub/stub2:= )
	!!stub/stub3:=
"
