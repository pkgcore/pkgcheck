EAPI=7

inherit pre-inherit

DESCRIPTION="Ebuild with misplaced pre-inherit eclass variable"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
SLOT="0"
LICENSE="BSD"

PRE_INHERIT_VAR="foo"
