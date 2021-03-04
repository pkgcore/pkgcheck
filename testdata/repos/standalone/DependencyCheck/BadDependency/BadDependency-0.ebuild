EAPI=7
DESCRIPTION="Ebuild with bad dependencies"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
SLOT="0"
LICENSE="BSD"
DEPEND="
	!DependencyCheck/BadDependency
	|| ( stub/stub1:= stub/stub2:= )
	!!stub/stub3:=
"
