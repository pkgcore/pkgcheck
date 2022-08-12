EAPI=7

DESCRIPTION="Ebuild with invalid BDEPEND"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
SLOT="0"
LICENSE="BSD"

BDEPEND="!DependencyCheck/InvalidRdepend"
DEPEND="!DependencyCheck/InvalidRdepend"
RDEPEND="!DependencyCheck/BadDependency"
PDEPEND="!DependencyCheck/BadDependency"
IDEPEND="!DependencyCheck/BadDependency"
