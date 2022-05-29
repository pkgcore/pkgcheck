# Copyright 2022 Gentoo Authors
# Distributed under the terms of the GNU General Public License v2

EAPI=8

EGIT_COMMIT=e12f045393dfa27b2730caae844f50c38f6afadb
MY_P=${PN}-${EGIT_COMMIT}
DESCRIPTION="Ebuild with pypi remote-id and a GitHub snapshot"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
SRC_URI="
	https://github.com/examplesoft/example/archive/v${PV}.tar.gz
		-> ${MY_P}.tar.gz
"

LICENSE="BSD"
SLOT="0"
