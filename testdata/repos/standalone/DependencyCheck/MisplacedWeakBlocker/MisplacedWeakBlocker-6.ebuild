EAPI=6

DESCRIPTION="Ebuild with misplaced weak blocker"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
SLOT="0"
LICENSE="BSD"

BDEPEND="!DependencyCheck/InvalidRdepend"
DEPEND="!DependencyCheck/BadDependency"
RDEPEND="!DependencyCheck/BadDependency"
PDEPEND="!DependencyCheck/BadDependency"
IDEPEND="!DependencyCheck/BadDependency"
