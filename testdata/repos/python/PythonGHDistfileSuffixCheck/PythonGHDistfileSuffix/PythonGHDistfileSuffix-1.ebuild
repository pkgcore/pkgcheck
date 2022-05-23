# Copyright 2022 Gentoo Authors
# Distributed under the terms of the GNU General Public License v2

EAPI=8

DESCRIPTION="Ebuild with pypi remote-id and missing .gh.tar.gz suffix"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
SRC_URI="
	https://github.com/examplesoft/example/archive/v${PV}.tar.gz
		-> ${P}.tar.gz
"

LICENSE="BSD"
SLOT="0"
