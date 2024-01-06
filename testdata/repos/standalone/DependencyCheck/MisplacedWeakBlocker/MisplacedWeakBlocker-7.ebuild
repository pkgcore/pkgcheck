EAPI=7

DESCRIPTION="Ebuild with invalid BDEPEND"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"

BDEPEND="!DependencyCheck/InvalidRdepend"
DEPEND="!DependencyCheck/InvalidRdepend"
RDEPEND="!DependencyCheck/BadDependency"
PDEPEND="!DependencyCheck/BadDependency"
IDEPEND="!DependencyCheck/BadDependency"
