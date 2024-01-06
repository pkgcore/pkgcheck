EAPI=6

DESCRIPTION="Ebuild with misplaced weak blocker"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"

BDEPEND="!DependencyCheck/InvalidRdepend"
DEPEND="!DependencyCheck/BadDependency"
RDEPEND="!DependencyCheck/BadDependency"
PDEPEND="!DependencyCheck/BadDependency"
IDEPEND="!DependencyCheck/BadDependency"
